"""Start or upgrade only this installation's idle companion, without opening UI."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
from entry import ROOT,bootstrap

def request(base,path,data=None,timeout=3):
    body=None if data is None else json.dumps(data).encode('utf-8')
    req=urllib.request.Request(base+path,data=body,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as response:return json.load(response)

def owned_listener(port):
    import psutil
    matches={c.pid for c in psutil.net_connections(kind='tcp') if c.status==psutil.CONN_LISTEN
             and c.laddr.port==port and c.laddr.ip in ('127.0.0.1','0.0.0.0','::1','::')}
    if len(matches)!=1:raise RuntimeError('Cannot verify ownership of the companion port.')
    process=psutil.Process(matches.pop());args=process.cmdline()
    expected=(ROOT/'python_embeded/python.exe').resolve()
    scripts={Path(arg).resolve() for arg in args if arg.lower().endswith('.py')}
    if (Path(process.exe()).resolve()!=expected or (ROOT/'runtime/entry.py').resolve() not in scripts
            or 'bridge' not in args):
        raise RuntimeError('This port belongs to another application or installation; automatic restart was skipped.')
    return process

def compatible(info):
    if info.get('app')!='toyxyz_motion_ai_tool' or info.get('protocol')!=1:
        raise RuntimeError('A different or incompatible application is using the companion port.')
    capabilities=set(info.get('capabilities',[]))
    return {'blender_process_lifetime','object_constraints','next_motion_context','atomic_cancel'}<=capabilities and 'image_pose_capture' not in capabilities

def ensure(port):
    bootstrap('ardy')
    base=f'http://127.0.0.1:{port}';restarted=False
    try:info=request(base,'/health')
    except urllib.error.HTTPError:raise RuntimeError('A different application is using the companion port.') from None
    except (OSError,TimeoutError):info=None
    if info is not None:
        if compatible(info):return dict(status='ready',restarted=False,instance=info['instance'],base=base)
        if info.get('active_job'):raise RuntimeError('Finish or cancel motion generation before updating the companion app.')
        process=owned_listener(port)
        # Recheck both identity and activity immediately before the shutdown.
        current=request(base,'/health')
        if current.get('instance')!=info.get('instance') or current.get('active_job'):
            raise RuntimeError('The companion state changed. Finish the active job, then click Start again.')
        request(base,'/shutdown',{})
        try:process.wait(timeout=45)
        except Exception as exc:raise RuntimeError('The old companion is still stopping. Try Start again shortly.') from exc
        restarted=True
    # A concurrent click may already have started the updated app.
    try:
        info=request(base,'/health',timeout=.5)
        if compatible(info):return dict(status='ready',restarted=restarted,instance=info['instance'],base=base)
        raise RuntimeError('The companion is still running older code.')
    except (OSError,TimeoutError):pass
    logpath=ROOT/'logs/companion_app_start.log';logpath.parent.mkdir(parents=True,exist_ok=True)
    with logpath.open('ab') as log:
        process=subprocess.Popen([str(ROOT/'python_embeded/python.exe'),'-X','utf8','-u',str(ROOT/'runtime/entry.py'),
            'bridge','--port',str(port),'--no-browser'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        try:
            info=request(base,'/health',timeout=.5)
            if compatible(info):return dict(status='ready',restarted=restarted,instance=info['instance'],base=base,pid=process.pid)
            raise RuntimeError('The companion started without the required features. Check the app folder in addon preferences.')
        except (OSError,TimeoutError):
            if process.poll() is not None:raise RuntimeError('The companion could not start. Check logs/companion_app_start.log.')
            time.sleep(.15)
    raise RuntimeError('Companion startup timed out. Check logs/companion_app_start.log.')

def main():
    from blender_owner import join
    join()
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8790)
    parser.add_argument('--result',type=Path);args=parser.parse_args()
    try:result=ensure(args.port)
    except Exception as exc:result=dict(status='failed',error=str(exc))
    if args.result:
        args.result.parent.mkdir(parents=True,exist_ok=True)
        temp=args.result.with_suffix('.partial');temp.write_text(json.dumps(result),encoding='utf-8');temp.replace(args.result)
    print(json.dumps(result),flush=True)
    return 0 if result['status']=='ready' else 1

if __name__=='__main__':raise SystemExit(main())
