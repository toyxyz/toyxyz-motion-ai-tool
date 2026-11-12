"""Local companion app for toyxyz_motion_ai_tool. No bpy imports."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
import uuid
import webbrowser

from entry import ROOT
from encoder_profiles import PROFILES
from motion_bridge_protocol import APP,VERSION,SCHEMA,validate


def health(url,timeout=2):
    with urllib.request.urlopen(url,timeout=timeout) as response:return json.load(response)


class Application:
    def __init__(self):
        self.id=uuid.uuid4().hex;self.lock=threading.RLock();self.jobs={};self.active=None
        self.encoder=None;self.encoder_precision=None;self.logs=[];self.closed=threading.Event()
        self.encoder_identity=None
        self.motion=None;self.motion_engine=None;self.mailbox=None;self.runner=None
        self.directory=ROOT/'results'/APP;self.directory.mkdir(parents=True,exist_ok=True)
        from blender_owner import identity,job_name
        self.process_created=identity();self.lifetime_job=job_name(self.id)
    def state(self):
        with self.lock:
            return dict(app=APP,protocol=VERSION,instance=self.id,status='ready',engines=['kimodo','motionbricks','ardy'],
                        pid=os.getpid(),process_created=self.process_created,installation_root=str(ROOT),lifetime_job=self.lifetime_job,
                        active_job=self.active,encoder_precision=self.encoder_precision,resident_motion=self.motion_state(),capabilities=['root_heading','root_height','delayed_curve_start','blender_process_lifetime','object_constraints','next_motion_context','atomic_cancel'],
                        jobs=[self.public(j) for j in list(self.jobs.values())[-12:]])
    def public(self,job):
        with self.lock:
            if job['status']=='running':
                try:
                    progress=json.loads((job['folder']/'progress.json').read_text(encoding='utf-8'))
                    value=float(progress['progress'])
                    if 0<=value<=100:
                        job.update(progress=max(job.get('progress',0),min(99,value)),message=progress['stage'],
                                   work_completed=progress.get('completed'),work_total=progress.get('total'))
                except (OSError,ValueError,KeyError,TypeError):pass
            return {k:v for k,v in job.items() if k not in ('process','request','folder','result')}
    def spawn(self,command,logname):
        log=(ROOT/'logs'/logname).open('w',encoding='utf-8');self.logs.append(log)
        return subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
    def motion_state(self):
        if self.motion is None or self.motion.poll() is not None:return None
        try:value=json.loads((self.mailbox/'state.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):value=dict(status='starting',model_load_count=0)
        return dict(value,engine=self.motion_engine,pid=self.motion.pid)
    def stop_motion(self):
        if self.motion is not None and self.motion.poll() is None:
            self.motion.terminate();self.motion.wait(timeout=20)
        self.motion=None;self.motion_engine=None;self.mailbox=None
    def ensure_motion(self,engine):
        if self.motion is not None and self.motion.poll() is None and self.motion_engine==engine:return self.motion
        self.stop_motion()
        self.mailbox=ROOT/'cache/sessions'/('motion-'+uuid.uuid4().hex);self.mailbox.mkdir(parents=True)
        self.motion_engine=engine
        self.motion=self.spawn([sys.executable,'-X','utf8','-u',str(ROOT/'runtime/motion_bridge_worker.py'),
                                '--serve','--engine',engine,'--mailbox',str(self.mailbox)],f'{APP}_resident_{self.mailbox.name}.log')
        return self.motion
    def stop_encoder(self,include_shared=False):
        if self.encoder is not None and self.encoder.poll() is None:
            self.encoder.terminate();self.encoder.wait(timeout=20)
        elif include_shared and self.encoder_identity:
            # Adopted services can predate this app process. Release only an exact
            # same-installation encoder, never an arbitrary process at that PID.
            import psutil
            info=self.encoder_identity
            try:
                try:
                    current=health(f'http://127.0.0.1:{PROFILES[self.encoder_precision]["port"]}/health')
                    if current.get('repo')==info.get('repo') and current.get('revision')==info.get('revision'):info=current
                except OSError:pass
                process=self.shared_encoder_process(info)
                if process is None:
                    raise RuntimeError('The shared encoder belongs to another installation; release skipped.')
                process.terminate();process.wait(timeout=20)
            except (psutil.NoSuchProcess,psutil.ZombieProcess):pass
            except (OSError,urllib.error.URLError):
                # A vanished endpoint already has no reachable shared encoder.
                pass
        self.encoder=None;self.encoder_precision=None;self.encoder_identity=None
    def shared_encoder_process(self,info):
        import psutil
        process=psutil.Process(info['pid']);args=process.cmdline()
        same_python=Path(process.exe()).resolve()==(ROOT/'python_embeded/python.exe').resolve()
        entry=str((ROOT/'runtime/entry.py').resolve()).casefold()
        direct=str((ROOT/'runtime/shared_encoder_service.py').resolve()).casefold()
        scripts={str(Path(arg).resolve()).casefold() for arg in args if arg.endswith('.py')}
        same_entry=bool(scripts & {entry,direct})
        role=('encoder' in args or direct in scripts)
        return process if same_python and same_entry and role else None
    def worker_failure(self,job,code):
        path=job['folder']/'error.json'
        logpath=ROOT/'logs'/f'{APP}_{job["id"]}.log'
        if path.is_file():
            try:
                error=json.loads(path.read_text(encoding='utf-8'))
                # Also keep the traceback in the advertised log if inherited stdio was unavailable.
                if not logpath.exists() or not logpath.stat().st_size:
                    logpath.write_text(error.get('traceback',''),encoding='utf-8')
                return f'{error.get("error_type","Error")}: {error.get("message","Generation failed.")}'
            except (OSError,ValueError):pass
        return f'Generation worker exited ({code & 0xffffffff:#010x}). Check logs/{APP}_{job["id"]}.log'
    def ensure_encoder(self,precision,job):
        if self.encoder_precision and self.encoder_precision!=precision:self.stop_encoder(include_shared=True)
        profile=PROFILES[precision];url=f'http://127.0.0.1:{profile["port"]}/health'
        def compatible(info):
            return info.get('precision')==precision and info.get('repo')==profile['repo'] and info.get('revision')==profile['revision'] and info.get('model_load_count')==1
        try:
            info=health(url)
        except Exception:info=None
        if info is not None:
            if not compatible(info):raise RuntimeError('An incompatible encoder is using this port.')
            owner=self.shared_encoder_process(info)
            if owner is not None:
                from process_owner import adopt
                adopt(owner.pid)
            self.encoder_precision=precision;self.encoder_identity=info
            return
        with self.lock:
            if self.closed.is_set() or job['status']=='cancelled':raise RuntimeError('The job was cancelled.')
            if self.encoder is not None and self.encoder.poll() is None and self.encoder_precision!=precision:self.encoder.terminate();self.encoder.wait(timeout=20)
            self.encoder_precision=precision
            self.encoder=self.spawn([sys.executable,'-X','utf8','-u',str(ROOT/'runtime/entry.py'),'encoder','--precision',precision],f'{APP}_encoder_{precision}.log')
        started=time.monotonic()
        while time.monotonic()-started<360:
            if job['status']=='cancelled':raise RuntimeError('The job was cancelled.')
            if self.encoder.poll() is not None:raise RuntimeError('The text encoder failed to start. Check the logs folder.')
            try:
                info=health(url)
                if not compatible(info):raise RuntimeError('The shared encoder configuration does not match.')
                self.encoder_identity=info
                return
            except (OSError,ValueError):time.sleep(.4)
        raise TimeoutError('Text encoder startup timed out.')
    def submit(self,data):
        data=validate(data)
        with self.lock:
            cancelling=self.runner if self.active and self.jobs[self.active]['status']=='cancelled' else None
        if cancelling is not None:cancelling.join(timeout=4)
        with self.lock:
            if self.closed.is_set():raise RuntimeError('The app is stopping.')
            if self.active:raise RuntimeError('Finish or cancel the active job first.')
            ident=uuid.uuid4().hex;folder=self.directory/ident;folder.mkdir()
            (folder/'request.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
            job=dict(id=ident,status='queued',engine=data['engine'],precision=data['precision'] if data['engine'] in ('kimodo','ardy') else 'fp32',message='Preparing job',
                     progress=0.0,created=time.time(),folder=folder,request=data,process=None,result=None)
            self.jobs[ident]=job;self.active=ident
            self.runner=threading.Thread(target=self.run,args=(job,),daemon=True);self.runner.start()
            return self.public(job)
    def run(self,job):
        try:
            with self.lock:
                if job['status']=='cancelled' or self.closed.is_set():return
                job.update(status='running',message='Preparing text encoder' if job['engine'] in ('kimodo','ardy') else 'Preparing MotionBricks')
                if self.motion_engine and self.motion_engine!=job['engine']:self.stop_motion()
            if job['engine'] in ('kimodo','ardy'):self.ensure_encoder(job['precision'],job)
            with self.lock:
                if job['status']=='cancelled':return
                job['message']='Generating motion'
                process=self.ensure_motion(job['engine'])
                job['process']=process
                job['worker_log']=f'logs/{APP}_resident_{self.mailbox.name}.log'
                command=self.mailbox/'command.json';temp=command.with_suffix('.partial')
                temp.write_text(json.dumps(dict(request=str(job['folder']/'request.json'),output=str(job['folder']/'result.json'))),encoding='utf-8');temp.replace(command)
            started=time.monotonic()
            while not (job['folder']/'result.json').is_file():
                if job['status']=='cancelled':return
                if (job['folder']/'error.json').is_file():raise RuntimeError(self.worker_failure(job,1))
                code=process.poll()
                if code is not None:raise RuntimeError(self.worker_failure(job,code))
                if job['engine']!='ardy' and time.monotonic()-started>900:raise TimeoutError('Motion generation timed out.')
                time.sleep(.05)
            if job['status']=='cancelled':return
            result=json.loads((job['folder']/'result.json').read_text(encoding='utf-8'))
            if result['status']!='succeeded':raise RuntimeError('Invalid result status.')
            with self.lock:
                if job['status']=='cancelled':return
                job.update(status='succeeded',progress=100.0,message='Generation complete. Blender applies the motion automatically.',result=result,
                           frame_count=result['frame_count'],elapsed_seconds=result['elapsed_seconds'],
                           worker_pid=result['worker_pid'],model_reused=result['model_reused'],model_load_count=result['model_load_count'])
        except BaseException as exc:
            with self.lock:
                if job['process'] is not None and job['process']==self.motion:self.stop_motion()
                if job['status']!='cancelled':job.update(status='failed',message=str(exc))
        finally:
            with self.lock:
                try:
                    if job['status']=='cancelled' and job['process'] is not None and job['process']==self.motion:
                        self.stop_motion()
                finally:
                    job['finished']=time.time()
                    if self.active==job['id']:self.active=None
                    (job['folder']/'status.json').write_text(json.dumps(self.public(job),ensure_ascii=False,indent=2),encoding='utf-8')
    def cancel(self,ident):
        with self.lock:
            job=self.jobs[ident]
            if job['status'] in ('queued','running'):
                job.update(status='cancelled',message='Job cancelled')
                process=job['process']
                if process is not None and process.poll() is None:process.terminate()
            return self.public(job)
    def release(self):
        with self.lock:
            if self.active:raise RuntimeError('Finish or cancel the job before releasing GPU memory.')
            self.stop_motion();self.stop_encoder(include_shared=True)
            # Also find services left by an earlier app session/profile. Never
            # terminate a service from a different installation.
            import psutil
            for precision,profile in PROFILES.items():
                try:
                    info=health(f'http://127.0.0.1:{profile["port"]}/health',timeout=.5)
                    if info.get('repo')!=profile['repo'] or info.get('revision')!=profile['revision']:continue
                    process=self.shared_encoder_process(info)
                    if process is not None:process.terminate();process.wait(timeout=20)
                except (OSError,ValueError,psutil.NoSuchProcess,psutil.ZombieProcess):pass
    def close(self,release_shared=False):
        self.closed.set()
        for ident in list(self.jobs):self.cancel(ident)
        with self.lock:self.stop_motion();self.stop_encoder(include_shared=release_shared)
        if self.runner and self.runner!=threading.current_thread():self.runner.join(timeout=25)
        for log in self.logs:log.close()


PAGE='''<!doctype html><html lang="en"><meta charset="utf-8"><title>toyxyz_motion_ai_tool</title>
<style>body{background:#171c25;color:#e6edf7;font:16px system-ui;margin:48px auto;max-width:900px;padding:24px}h1{color:#73dcc5}button{background:#30455f;color:white;border:0;border-radius:6px;padding:12px;margin:5px}pre{white-space:pre-wrap;background:#232d3b;padding:24px;border-radius:12px}small{color:#a8b8cc}</style>
<h1>toyxyz_motion_ai_tool</h1><p>External motion application for Blender</p><p>Author SOMA pose targets and prompt blocks in Blender. AI models run in this app, outside Blender.</p>
<button onclick="post('/release')">Release GPU</button><button onclick="post('/shutdown')">Stop App</button><p>Motion models stay in GPU memory until released or replaced by another model.</p><pre id="status">Connecting...</pre><small>Closing this browser tab keeps the app running. Release GPU unloads motion and text models. Stop App closes the app and its workers.</small>
<script>async function post(p){let r=await fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});let d=await r.json();if(!r.ok)alert(d.error||'Failed')}async function update(){try{let d=await(await fetch('/health')).json();document.getElementById('status').textContent='Status: ready\\nMotion model: '+(d.resident_motion?d.resident_motion.engine+' · '+d.resident_motion.status:'not loaded')+'\\nEncoder: '+(d.encoder_precision||'not loaded')+'\\n\\n'+d.jobs.map(j=>j.engine+' · '+j.status+'\\n'+j.message).join('\\n\\n')}catch(e){document.getElementById('status').textContent='The app is stopped or disconnected.'}}setInterval(update,1200);update()</script></html>'''


def serve(port=8790,open_browser=False,application=None):
    app=application or Application();base=f'http://127.0.0.1:{port}'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,data,kind='application/json; charset=utf-8'):
            payload=data.encode('utf-8') if isinstance(data,str) else json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(payload)));self.send_header('Cache-Control','no-store');self.end_headers()
            try:self.wfile.write(payload)
            except (BrokenPipeError,ConnectionResetError):pass
        def safe(self):
            if self.headers.get('Host') not in (f'127.0.0.1:{port}',f'localhost:{port}'):raise ValueError('Invalid Host')
            if self.headers.get('Origin') not in (None,base,f'http://localhost:{port}'):raise PermissionError('Requests from other websites are not allowed.')
        def do_GET(self):
            try:
                self.safe()
                if self.path=='/':return self.send(200,PAGE,'text/html; charset=utf-8')
                if self.path=='/health':return self.send(200,app.state())
                if self.path=='/skeleton':return self.send(200,SCHEMA)
                parts=self.path.strip('/').split('/')
                if len(parts) in (2,3) and parts[0]=='jobs' and parts[1] in app.jobs:
                    job=app.jobs[parts[1]]
                    if len(parts)==2:return self.send(200,app.public(job))
                    if parts[2]=='result' and job['status']=='succeeded':return self.send(200,job['result'])
                self.send(404,dict(error='Not found'))
            except PermissionError as exc:self.send(403,dict(error=str(exc)))
            except Exception as exc:self.send(400,dict(error=str(exc)))
        def do_POST(self):
            try:
                self.safe()
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('JSON required')
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=24*1024**2:raise ValueError('Request size limit')
                data=json.loads(self.rfile.read(size))
                parts=self.path.strip('/').split('/')
                if self.path=='/jobs':return self.send(202,app.submit(data))
                if self.path=='/release':app.release();return self.send(200,dict(status='released'))
                if self.path=='/shutdown':
                    self.send(200,dict(status='stopping'));threading.Thread(target=server.shutdown,daemon=True).start();return
                parts=self.path.strip('/').split('/')
                if len(parts)==3 and parts[0]=='jobs' and parts[2]=='cancel' and parts[1] in app.jobs:return self.send(200,app.cancel(parts[1]))
                self.send(404,dict(error='Not found'))
            except PermissionError as exc:self.send(403,dict(error=str(exc)))
            except (ValueError,KeyError) as exc:self.send(400,dict(error=str(exc)))
            except RuntimeError as exc:self.send(409,dict(error=str(exc)))
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
    print(f'{APP}: {base}',flush=True)
    if open_browser:webbrowser.open(base)
    try:server.serve_forever(poll_interval=.3)
    finally:server.server_close();app.close(release_shared=True)
