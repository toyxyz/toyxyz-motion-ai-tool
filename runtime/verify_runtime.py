"""Real-runtime portability checks, including original noise replay and shared-encoder identity."""
import importlib
import ctypes
import json
import locale
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from entry import ROOT
from encoder_profiles import PROFILES

def doctor(engine):
    import numpy
    import psutil
    import torch
    expected=ROOT.resolve()
    modules=[numpy,torch]
    extra={}
    if engine=='motionbricks':
        for name in ['warp','newton','tensorrt','onnxruntime','motionbricks']:
            module=importlib.import_module(name);modules.append(module)
            extra[name]=getattr(module,'__version__',None)
    else:
        import transformers
        modules += [transformers,importlib.import_module(engine),importlib.import_module('motion_correction._motion_correction')]
        extra['transformers']=transformers.__version__
    paths={module.__name__:module.__file__ for module in modules}
    assert sys.flags.isolated==1 and sys.flags.no_site==1 and sys.flags.ignore_environment==1
    assert sys.prefix==str(ROOT/'python_embeded')
    for path in [*paths.values(),*sys.path]:
        if path and not Path(path).resolve().is_relative_to(expected):raise RuntimeError('External runtime dependency: '+str(path))
    assert torch.cuda.is_available();value=torch.ones(16,device='cuda').sum().item();assert value==16
    native_paths=sorted({mapping.path for mapping in psutil.Process().memory_maps() if mapping.path.lower().endswith(('.dll','.pyd'))})
    forbidden=['nvidia gpu computing toolkit','microsoft visual studio','\\envs\\','\\appdata\\local\\programs\\python']
    unexpected=[path for path in native_paths if not Path(path).resolve().is_relative_to(expected)
                and any(part in path.lower() for part in forbidden)]
    if unexpected:raise RuntimeError('External development runtime DLL was loaded: '+str(unexpected))
    report=dict(status='passed',engine=engine,python=sys.executable,version=sys.version,isolated=sys.flags.isolated,
                numpy=numpy.__version__,torch=torch.__version__,gpu=torch.cuda.get_device_name(),modules=paths,
                versions=extra,path=os.environ.get('PATH'),cuda_path=os.environ.get('CUDA_PATH'),rss=psutil.Process().memory_info().rss,
                loaded_native_libraries=native_paths,external_development_runtime_dlls=unexpected,
                native_file_locale=locale.setlocale(locale.LC_CTYPE))
    report['windows_process_code_page']=ctypes.windll.kernel32.GetACP()
    assert report['windows_process_code_page']==65001
    (ROOT/'results'/f'doctor_{engine}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)

def main(precision='all'):
    import numpy as np
    import pynvml
    report=dict(status='running',python=sys.executable,profiles={},scope='Portable execution and numerical regression, not semantic quality certification')
    path=ROOT/'results/portable_verification.json';owned=[];logs=[]
    pynvml.nvmlInit();gpu=pynvml.nvmlDeviceGetHandleByIndex(0)
    def launch(role,engine='ardy',mode=None,hold=False):
        log=(ROOT/'logs'/f'verify_{role}_{engine}_{mode or "default"}.log').open('w',encoding='utf-8');logs.append(log)
        command=[sys.executable,'-X','utf8','-u',str(ROOT/'runtime/entry.py'),role,'--engine',engine]
        if mode:command+=['--precision',mode]
        if hold:command+=['--hold']
        process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.PIPE)
        owned.append(process);return process
    def stop_all():
        for process in reversed(owned):
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        owned.clear()
        for log in logs:log.close()
        logs.clear()
    def wait_report(process,target,timeout=420):
        start=time.monotonic()
        while time.monotonic()-start<timeout:
            if target.exists():
                try:data=json.loads(target.read_text(encoding='utf-8'))
                except json.JSONDecodeError:data={}
                if data.get('status')=='failed':raise RuntimeError(str(data))
                if data.get('status')=='passed':return data
            if process.poll() is not None:raise RuntimeError(f'Worker failed with {process.returncode}: {target}')
            time.sleep(.5)
        raise TimeoutError(str(target))
    try:
        for engine in ('kimodo','ardy','motionbricks'):
            target=ROOT/f'results/doctor_{engine}.json';target.write_text('{}')
            process=launch('doctor',engine);wait_report(process,target);assert process.wait(timeout=20)==0
        stop_all()
        for mode in PROFILES if precision=='all' else [precision]:
            for port in [PROFILES[mode]['port'],7860,2333]:
                with socket.socket() as sock:
                    if sock.connect_ex(('127.0.0.1',port))==0:raise RuntimeError(f'Port {port} is already in use')
            baseline=pynvml.nvmlDeviceGetMemoryInfo(gpu).used
            peak=[baseline];done=threading.Event()
            def monitor():
                while not done.wait(.1):peak[0]=max(peak[0],pynvml.nvmlDeviceGetMemoryInfo(gpu).used)
            thread=threading.Thread(target=monitor,daemon=True);thread.start()
            try:
                server=launch('encoder',mode=mode);started=time.monotonic();identity=None
                while identity is None:
                    if server.poll() is not None:raise RuntimeError(mode+' encoder failed')
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{PROFILES[mode]["port"]}/health',timeout=2) as response:identity=json.load(response)
                    except Exception:
                        if time.monotonic()-started>360:raise
                        time.sleep(.5)
                trials={}
                for engine in ('kimodo','ardy'):
                    target=ROOT/f'results/verification/{mode}/{engine}/report.json'
                    target.parent.mkdir(parents=True,exist_ok=True);target.write_text('{}')
                    process=launch('sample',engine,mode,hold=True)
                    trial=wait_report(process,target)
                    if trial['encoder_instance']!=identity['instance_id']:raise RuntimeError('Encoder was not shared')
                    for case in trial['cases']:
                        if case['embedding_cosine_vs_previous']<(.9999 if mode=='bf16' else .999999):
                            raise RuntimeError('Unexpected encoder numerical regression')
                        if mode!='bf16' and case['previous_result_difference']['world_mpjpe_cm']>.01:
                            raise RuntimeError('Quantized motion changed after packaging')
                    trials[engine]=trial
                for case in ('walk_0','fall_0'):
                    a=np.load(ROOT/f'results/verification/{mode}/kimodo/{case}_embedding.npy')
                    b=np.load(ROOT/f'results/verification/{mode}/ardy/{case}_embedding.npy')
                    assert np.array_equal(a,b),'Shared vectors differ between engines'
                resident=pynvml.nvmlDeviceGetMemoryInfo(gpu).used
                report['profiles'][mode]=dict(status='passed',model_load_count=identity['model_load_count'],encoder_instance=identity['instance_id'],
                    workers=trials,background_bytes=baseline,both_models_resident_bytes=resident,observed_peak_bytes=peak[0])
                path.write_text(json.dumps(report,indent=2),encoding='utf-8')
                print('PROFILE_PASSED '+mode,flush=True)
            finally:
                done.set();thread.join();stop_all()
        target=ROOT/'results/verification/motionbricks/report.json';target.parent.mkdir(parents=True,exist_ok=True);target.write_text('{}')
        process=launch('sample','motionbricks');report['motionbricks']=wait_report(process,target,timeout=600)
        assert process.wait(timeout=30)==0
        report['status']='passed'
    except BaseException as exc:
        report.update(status='failed',error_type=type(exc).__name__,error=str(exc));raise
    finally:
        stop_all();pynvml.nvmlShutdown()
        path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(dict(status=report['status'],profiles=list(report['profiles'])),indent=2),flush=True)
