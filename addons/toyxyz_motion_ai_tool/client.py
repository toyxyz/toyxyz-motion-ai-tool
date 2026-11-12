"""Only standard-library networking in background threads; bpy is main-thread only."""
import json
import queue
import threading
from pathlib import Path
import urllib.error
import urllib.request

APP='toyxyz_motion_ai_tool'
events=queue.Queue();commands=queue.Queue()
thread=None;stop_event=threading.Event()
submission_token=0
state=dict(connected=False,message='Connect to the external app.',job_id='',job_status='',result=None,instance=None,
           app_running=False,connecting=False,stopping=False,
           scene_uid=None,input_uuid=None,applied_job=None,auto_apply_pending=False,auto_apply_error=False,
           resident_motion=None,encoder_precision=None,capabilities=[],sequence=None,sequence_jobs=[],pending_connect=None,
           progress=None,job_progress=0,progress_stage='',connection_error='')


def request(base,path,data=None,timeout=4):
    body=None if data is None else json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
    req=urllib.request.Request(base+path,data=body,headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=timeout) as response:return json.load(response)
    except urllib.error.HTTPError as exc:
        try:message=json.load(exc).get('error',str(exc))
        except Exception:message=str(exc)
        raise RuntimeError(message) from None


def start(base,scene_uid,runtime_root=None):
    global thread,stop_event,commands
    stop();commands=queue.Queue();stop_event=threading.Event()
    event=stop_event;incoming=commands;outgoing=events
    from . import lifetime
    if runtime_root is None:
        config=Path(__file__).with_name('app_location.json')
        runtime_root=json.loads(config.read_text(encoding='utf-8'))['root'] if config.exists() else Path(__file__).resolve().parents[2]
    def emit(kind,payload,token=None):
        if not event.is_set():outgoing.put((kind,scene_uid,payload,token))
    def run():
        job=None;job_token=None;instance=None;last_error=None
        while not event.is_set():
            try:
                while not event.is_set():
                    try:command,payload,token=incoming.get_nowait()
                    except queue.Empty:break
                    if command=='submit':
                        try:
                            result=request(base,'/jobs',payload,timeout=12)
                            job=result['id'];job_token=token;emit('job',result,job_token)
                        except Exception as exc:emit('job_error',str(exc),token)
                    elif command=='cancel' and job and token==job_token:
                        emit('job',request(base,f'/jobs/{job}/cancel',{}),job_token);job=None
                    elif command=='release':
                        request(base,'/release',{},timeout=60)
                        emit('released',None)
                    elif command=='shutdown':
                        request(base,'/shutdown',{});emit('stopped',None);event.set()
                if event.is_set():break
                info=request(base,'/health')
                if event.is_set():break
                if info.get('app')!=APP or info.get('protocol')!=1:raise RuntimeError('This address belongs to a different application.')
                lifetime.bind(info,runtime_root)
                if instance is not None and instance!=info['instance']:
                    job=None;emit('reset',None)
                instance=info['instance'];emit('health',info);last_error=None
                if job:
                    status=request(base,f'/jobs/{job}');emit('job',status,job_token)
                    if status['status']=='succeeded':
                        result=request(base,f'/jobs/{job}/result',timeout=60);result['job_id']=job
                        emit('result',result,job_token);job=None
                    elif status['status'] in ('failed','cancelled'):job=None
            except Exception as exc:
                text=('The companion app is unavailable. Click Start to start or reconnect.'
                      if isinstance(exc,(urllib.error.URLError,ConnectionError,TimeoutError)) else str(exc))
                if text!=last_error:emit('error',text);last_error=text
            event.wait(.15 if job else .75)
        if job:
            # A reconnect or file load can stop polling before the queued Cancel
            # is processed. Only cancel the job owned by this connection.
            try:request(base,f'/jobs/{job}/cancel',{})
            except (OSError,RuntimeError):pass
    thread=threading.Thread(target=run,daemon=True,name='toyxyz-motion-client');thread.start()


def stop():
    global thread,events
    stop_event.set()
    events=queue.Queue()
    thread=None


def send(command,payload=None):
    global submission_token
    if command=='submit':submission_token+=1
    commands.put((command,payload,submission_token))
