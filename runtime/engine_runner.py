"""Adapters around unchanged upstream entry points, with one shared text encoder."""
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import runpy
import sys
import time

from entry import ROOT
from encoder_profiles import PROFILES
from shared_encoder_client import SharedEncoderClient,inject_shared_encoder

def connect(engine,precision):
    os.environ['MOTION_ENCODER_PRECISION']=precision
    os.environ['MOTION_ENCODER_URL']=f'http://127.0.0.1:{PROFILES[precision]["port"]}'
    return SharedEncoderClient(engine,precision=precision)

def demo(engine,precision):
    if engine=='motionbricks':return motionbricks()
    import viser
    original_server=viser.ViserServer
    class LocalViserServer(original_server):
        def __init__(self,*args,**kwargs):
            kwargs['host']='127.0.0.1'
            super().__init__(*args,**kwargs)
    viser.ViserServer=LocalViserServer
    client=connect(engine,precision)
    inject_shared_encoder(engine,client)
    namespace=ROOT/'cache/sessions'/precision/client.identity['fingerprint']/engine
    namespace.mkdir(parents=True,exist_ok=True);os.chdir(namespace)
    os.environ['kimodo_EMBED_CACHE_DIR']=str(namespace/'embeddings')
    if engine=='kimodo':
        sys.argv=['kimodo-demo','--model','Kimodo-SOMA-RP-v1.2']
        runpy.run_module('kimodo.demo',run_name='__main__')
    else:
        sys.path.insert(0,str(ROOT/'engines/ardy/scripts'))
        sys.argv=['ardy-demo','--no-compile']
        runpy.run_path(str(ROOT/'engines/ardy/scripts/run_demo.py'),run_name='__main__')

def sample(engine,precision,count=2,hold=False):
    if engine=='motionbricks':return motionbricks_sample()
    import numpy as np
    import torch
    client=connect(engine,precision)
    module=importlib.import_module(f'{engine}.model.load_model')
    original=module.load_model;cached=[]
    def load(*args,**kwargs):
        if not cached:
            kwargs['text_encoder']=client;cached.append(original(*args,**kwargs))
        return cached[0]
    module.load_model=load
    importlib.import_module(engine).load_model=load
    importlib.import_module(f'{engine}.model').load_model=load
    out=ROOT/f'results/verification/{precision}/{engine}';out.mkdir(parents=True,exist_ok=True)
    cases=[('walk_0','A person walks forward.',0),('fall_0','A person falls to the ground.',0)]
    report=dict(status='running',engine=engine,precision=precision,encoder_instance=client.identity['instance_id'],
                encoder_pid=client.identity['pid'],python=sys.executable,cases=[])
    report_file=out/'report.json'
    original_randn=torch.randn;current={}
    def randn(*args,**kwargs):
        caller=inspect.currentframe().f_back.f_code.co_filename.replace('\\','/')
        if not caller.endswith(('/kimodo_model.py','/ardy_model.py')):return original_randn(*args,**kwargs)
        index=len(current['sha256']);array=current['noise'][f'noise_{index}']
        shape=tuple(args[0]) if len(args)==1 and isinstance(args[0],(tuple,list,torch.Size)) else tuple(args)
        if shape!=array.shape:raise RuntimeError('Recorded motion noise shape changed')
        current['sha256'].append(hashlib.sha256(array.tobytes()).hexdigest())
        return torch.tensor(array,device=kwargs.get('device','cpu'),dtype=kwargs.get('dtype',torch.float32))
    torch.randn=randn
    try:
        for name,prompt,seed in cases[:count]:
            with np.load(ROOT/f'testdata/{engine}/{name}_noise.npz',allow_pickle=False) as noise:
                current.update(noise=noise,sha256=[])
                destination=out/name
                sys.argv=[engine,prompt,'--model','Kimodo-SOMA-RP-v1.2' if engine=='kimodo' else 'ARDY-SOMA-RP-30FPS-Horizon60',
                          '--duration','2' if engine=='kimodo' else '4','--seed',str(seed),'--output',str(destination)]
                started=time.perf_counter()
                if engine=='kimodo':
                    sys.argv+=['--diffusion_steps','100','--bvh']
                    runpy.run_module('kimodo.scripts.generate',run_name='__main__')
                else:runpy.run_path(str(ROOT/'engines/ardy/scripts/generate.py'),run_name='__main__')
                torch.cuda.synchronize()
                if len(current['sha256'])!=len(noise.files):raise RuntimeError('Recorded noise calls changed')
            embedding=client([prompt])[0].cpu().numpy()
            np.save(out/f'{name}_embedding.npy',embedding)
            from comparison_metrics import metrics
            with np.load(destination.with_suffix('.npz'),allow_pickle=False) as clip,\
                 np.load(ROOT/f'testdata/{engine}/{precision}/{name}.npz',allow_pickle=False) as reference:
                for key in clip.files:
                    if clip[key].dtype.kind in 'fc' and not np.isfinite(clip[key]).all():raise RuntimeError('Non-finite motion')
                frames=len(clip['local_rot_mats'])
                assert frames==(60 if engine=='kimodo' else 120)
                difference=metrics(reference,clip)
            with np.load(ROOT/f'testdata/{engine}/{precision}/{name}_embeddings.npz') as saved:
                ref=saved['embedding_0'].reshape(embedding.shape).astype(np.float64)
                value=embedding.astype(np.float64)
                cosine=float(np.sum(ref*value)/np.linalg.norm(ref)/np.linalg.norm(value))
                max_embedding_error=float(np.max(np.abs(ref-value)))
            case=dict(id=name,frames=frames,elapsed_s=time.perf_counter()-started,noise_sha256=current['sha256'],
                      embedding_cosine_vs_previous=cosine,embedding_max_abs_error=max_embedding_error,
                      previous_result_difference=difference)
            report['cases'].append(case)
            report_file.write_text(json.dumps(report,indent=2),encoding='utf-8')
        import numpy,transformers
        native=importlib.import_module('motion_correction._motion_correction')
        report.update(status='passed',numpy=numpy.__version__,transformers=transformers.__version__,
                      native_extension=native.__file__,torch_path=torch.__file__,cuda_allocated_bytes=torch.cuda.memory_allocated(),
                      encoder_final=client.health())
        report_file.write_text(json.dumps(report,indent=2),encoding='utf-8')
        if hold:sys.stdin.read()
    except BaseException as exc:
        report.update(status='failed',error_type=type(exc).__name__,error=str(exc));raise
    finally:
        torch.randn=original_randn
        report_file.write_text(json.dumps(report,indent=2),encoding='utf-8')

def motionbricks(test=False):
    os.chdir(ROOT/'engines/motionbricks')
    from native_paths import configure_warp
    configure_warp()
    sys.argv=['motionbricks','--model','soma','--model-precision','fp32']
    if test:sys.argv+=['--test','--num-frames','3']
    runpy.run_module('app.inbetweener_demo',run_name='__main__')

def motionbricks_sample():
    import numpy as np
    os.chdir(ROOT/'engines/motionbricks')
    from native_paths import configure_warp
    configure_warp()
    sys.path.insert(0,str(ROOT/'engines/motionbricks/docs/examples'))
    started=time.perf_counter()
    example=runpy.run_path(str(ROOT/'engines/motionbricks/docs/examples/generate_once.py'),run_name='portable_sample')
    motions=example['generate']('soma')
    assert len(motions)==2 and all(np.isfinite(x).all() and 18<=len(x)<=58 for x in motions)
    out=ROOT/'results/verification/motionbricks';out.mkdir(parents=True,exist_ok=True)
    np.savez(out/'walk_sequence.npz',**{f'segment_{i}':v for i,v in enumerate(motions)})
    with np.load(ROOT/'testdata/motionbricks/walk_sequence.npz') as ref:
        differences=[float(np.max(np.abs(ref[f'segment_{i}']-v))) if ref[f'segment_{i}'].shape==v.shape else None
                     for i,v in enumerate(motions)]
    report=dict(status='passed',python=sys.executable,runtime='official TensorRT',segments=[list(x.shape) for x in motions],
                max_abs_difference_vs_previous=differences,elapsed_s=time.perf_counter()-started)
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
