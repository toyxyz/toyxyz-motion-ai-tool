"""Local control panel and ownership-based lifecycle management."""
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from entry import ROOT
from encoder_profiles import PROFILES
from installer import settings,model_status

PORT=8788

def gpu_info():
    try:
        import pynvml
        pynvml.nvmlInit();handle=pynvml.nvmlDeviceGetHandleByIndex(0)
        memory=pynvml.nvmlDeviceGetMemoryInfo(handle);name=pynvml.nvmlDeviceGetName(handle)
        result=dict(name=name.decode() if isinstance(name,bytes) else name,total=memory.total,free=memory.free,used=memory.used)
        pynvml.nvmlShutdown()
        result['recommended']='bf16' if memory.free>=20*1024**3 else 'int8' if memory.free>=12*1024**3 else 'nf4' if memory.free>=9*1024**3 else None
        return result
    except Exception:return None

def request_json(url,timeout=2):
    with urllib.request.urlopen(url,timeout=timeout) as response:return json.load(response)

class Manager:
    def __init__(self):
        self.children=[];self.logs=[];self.lock=threading.RLock()
        self.state=dict(state='idle',message='Choose a precision and click Start.',config=settings(),demos={})
        self.cancel=threading.Event();self.thread=None
    def spawn(self,role,engine='ardy',precision=None,test=False):
        log=(ROOT/'logs'/f'{role}_{engine}_{precision or "default"}.log').open('w',encoding='utf-8')
        cmd=[sys.executable,'-X','utf8','-u',str(ROOT/'runtime/entry.py'),role,'--engine',engine]
        if precision:cmd+=['--precision',precision]
        if test:cmd+=['--test']
        p=subprocess.Popen(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        self.children.append(p);self.logs.append(log);return p
    def snapshot(self):
        with self.lock:
            result=dict(self.state)
            required=[p for p in self.children if any(role in p.args for role in ('encoder','demo'))]
            if result['state']=='ready' and any(p.poll() is not None for p in required):
                result.update(state='failed',message='A demo stopped. Stop All, then start again.')
            return dict(result,gpu=gpu_info())
    def start(self,config):
        precision=config.get('precision','bf16');engines=config.get('engines',['kimodo','ardy'])
        if precision not in PROFILES or not engines or any(e not in ('kimodo','ardy') for e in engines):raise ValueError('Invalid configuration.')
        with self.lock:
            active=[p for p in self.children if p.poll() is None and 'motionbricks' not in p.args]
            if active or (self.thread and self.thread.is_alive()):raise RuntimeError('Stop the running demos first.')
            if model_status(precision):raise RuntimeError('The selected model is missing. Run install.cmd -Precision '+precision+'.')
            self.cancel.clear();self.state=dict(state='starting',message='Preparing the shared text encoder.',config=dict(precision=precision,engines=engines),demos={})
            (ROOT/'settings.json').write_text(json.dumps(self.state['config'],indent=2),encoding='utf-8')
            self.thread=threading.Thread(target=self._start,args=(precision,engines),daemon=True);self.thread.start()
    def _start(self,precision,engines):
        try:
            for port in [PROFILES[precision]['port']]+[7860 if e=='kimodo' else 2333 for e in engines]:
                with socket.socket() as sock:
                    if sock.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('A previous demo is still running. Close it first.')
            server=self.spawn('encoder',precision=precision)
            start=time.monotonic();identity=None
            while not self.cancel.is_set():
                if server.poll() is not None:raise RuntimeError('Encoder startup failed. Check the logs folder.')
                try:identity=request_json(f'http://127.0.0.1:{PROFILES[precision]["port"]}/health');break
                except Exception:
                    if time.monotonic()-start>360:raise TimeoutError('Encoder startup timed out.')
                    self.cancel.wait(.5)
            if self.cancel.is_set():return
            if identity['precision']!=precision or identity['model_load_count']!=1:raise RuntimeError('Cannot verify the encoder state.')
            self.state.update(message='Preparing model demos.',encoder=identity)
            pending={e:(self.spawn('demo',e,precision),7860 if e=='kimodo' else 2333) for e in engines}
            start=time.monotonic()
            while pending and not self.cancel.is_set():
                for engine,(process,port) in list(pending.items()):
                    if process.poll() is not None:raise RuntimeError(engine+' failed to start. Check the logs folder.')
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}',timeout=1) as response:
                            if response.status==200:
                                self.state['demos'][engine]=f'http://127.0.0.1:{port}';del pending[engine]
                    except Exception:pass
                if time.monotonic()-start>300:raise TimeoutError('Demo startup timed out.')
                self.cancel.wait(.5)
            if not self.cancel.is_set():self.state.update(state='ready',message='Demos are ready. Open them with the buttons below.')
        except Exception as exc:
            self._cleanup();self.state.update(state='failed',message=str(exc),demos={})
    def _cleanup(self):
        import psutil
        for process in reversed(self.children):
            if process.poll() is not None:continue
            try:
                for child in reversed(psutil.Process(process.pid).children(recursive=True)):
                    try:child.terminate()
                    except psutil.NoSuchProcess:pass
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            except psutil.NoSuchProcess:pass
        self.children.clear()
        for log in self.logs:log.close()
        self.logs.clear()
    def stop(self):
        self.cancel.set()
        if self.thread and self.thread.is_alive():self.thread.join(timeout=8)
        self._cleanup();self.state.update(state='idle',message='All owned demos stopped.',demos={})
    def motionbricks(self):
        if any(p.poll() is None and 'motionbricks' in p.args for p in self.children):raise RuntimeError('MotionBricks is already running.')
        self.spawn('motionbricks','motionbricks')

def serve_ui(open_browser=True):
    manager=Manager()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,body,kind='application/json; charset=utf-8'):
            raw=body if isinstance(body,bytes) else json.dumps(body,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store');self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        def do_GET(self):
            if self.path=='/':return self.send(200,(ROOT/'runtime/panel.html').read_bytes(),'text/html; charset=utf-8')
            if self.path=='/status':return self.send(200,manager.snapshot())
            self.send(404,dict(error='Not found'))
        def do_POST(self):
            allowed={f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'}
            origin=self.headers.get('Origin')
            if origin not in allowed or not self.headers.get('Content-Type','').startswith('application/json'):
                return self.send(403,dict(error='Use this app window.'))
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<4096:raise ValueError('Invalid request.')
                data=json.loads(self.rfile.read(length))
                if self.path=='/start':manager.start(data)
                elif self.path=='/stop':manager.stop()
                elif self.path=='/motionbricks':manager.motionbricks()
                elif self.path=='/exit':
                    manager.stop();threading.Thread(target=server.shutdown,daemon=True).start()
                else:raise ValueError('Unknown request.')
                self.send(200,dict(ok=True))
            except Exception as exc:self.send(400,dict(error=str(exc)))
    server=ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    print(f'MotionAI: http://127.0.0.1:{PORT}',flush=True)
    if open_browser:webbrowser.open(f'http://127.0.0.1:{PORT}')
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:manager.stop();server.server_close()
