"""Real RNA with synthetic connection events: defer generation until connected."""
import json,socket,sys,time
from pathlib import Path
from types import SimpleNamespace
import bpy,addon_utils
ROOT=Path(__file__).resolve().parents[1];installed='--installed' in sys.argv
if not installed:sys.path.insert(0,str(ROOT/'addons'))
addon_utils.enable('toyxyz_motion_ai_tool',default_set=False)
import toyxyz_motion_ai_tool as addon
from toyxyz_motion_ai_tool import rig,timeline as t,client,generation
report=dict(status='running',installed=installed,checks=[]);original=(client.start,client.send,client.request,addon.preferences)
owned=None;test_base=None
try:
    scene=bpy.context.scene;scene.render.fps=30
    bpy.ops.toyxyz_motion_ai_tool.create_soma();s=addon.rig_store.settings(scene)
    a=s.blocks[0];t.set_range(a,0,60);b=t.add(scene)
    starts=[];sent=[];client.start=lambda *args:starts.append(args);client.send=lambda *args:sent.append(args)
    caps=['blender_process_lifetime','object_constraints','next_motion_context','atomic_cancel']
    client.request=lambda *args,**kw:dict(app=client.APP,protocol=1,capabilities=caps)
    def reset():
        while not client.events.empty():client.events.get_nowait()
        client.state.update(connected=False,connecting=False,stopping=False,scene_uid=None,job_status='',pending_connect=None,sequence=None,
                            auto_apply_pending=False,auto_apply_error=False,result=None)
        starts.clear();sent.clear();t.select(s,0)
    def ready():client.events.put(('health',s.scene_uid,dict(instance='test',resident_motion=None,capabilities=caps)))
    reset();assert bpy.ops.toyxyz_motion_ai_tool.generate()=={'FINISHED'}
    assert len(starts)==1 and not sent and client.state['job_status']=='connecting'
    assert client.state['pending_connect']['blocks'][0]['uid']==a.uid
    client.events.put(('error',s.scene_uid,'Connection refused during app startup'))
    addon.timer()
    assert client.state['pending_connect'] and client.state['connecting'] and not sent
    assert client.state['message']=='Waiting for the companion app to start and connect...'
    # The original clicked selection remains the request even if selection changes.
    t.select(s,1);ready();addon.timer()
    assert client.state['pending_connect'] is None and len(sent)==1
    assert sent[0][0]=='submit' and [v['uid'] for v in sent[0][1]['blocks']]==[a.uid]
    addon.timer();assert len(sent)==1
    report['checks'].append('Generate uses Start/connect, masks transient startup connection errors, waits for health and submits the original selected block exactly once')
    reset();assert bpy.ops.toyxyz_motion_ai_tool.generate()=={'FINISHED'}
    assert bpy.ops.toyxyz_motion_ai_tool.app_control(command='cancel')=={'FINISHED'}
    ready();addon.timer()
    assert client.state['pending_connect'] is None and not any(v[0]=='submit' for v in sent)
    report['checks'].append('Cancel during connection prevents later successful health events from submitting a generation')
    reset();bpy.ops.toyxyz_motion_ai_tool.generate()
    client.state['pending_connect']['started']=time.monotonic()-generation.CONNECT_TIMEOUT-1
    addon.timer();assert client.state['job_status']=='failed' and client.state['pending_connect'] is None and not sent
    assert 'click Start' in client.state['message'] and client.state['progress'] is None
    ready();addon.timer();assert not sent
    report['checks'].append('Connection timeout reports Start App and never silently submits when a late connection arrives')
    reset();bpy.ops.toyxyz_motion_ai_tool.generate();old=a.prompt;a.prompt='Changed during connection'
    ready();addon.timer()
    assert client.state['pending_connect'] is None and client.state['job_status']=='failed' and not sent
    a.prompt=old
    reset();bpy.ops.toyxyz_motion_ai_tool.generate();addon.on_load(None);ready();addon.timer()
    assert not sent and client.state['pending_connect'] is None
    report['checks'].append('Changed source block settings or loading another file cancels the pending request before submission')
    reset();client.state.update(connected=True,scene_uid=s.scene_uid)
    assert bpy.ops.toyxyz_motion_ai_tool.generate()=={'FINISHED'}
    assert not starts and len(sent)==1 and sent[0][0]=='submit'
    report['checks'].append('An already connected scene submits directly without reconnecting')
    # Real app startup/handshake on an isolated port. Intercept only submission:
    # no neural model is loaded and the user's service is never contacted.
    reset();client.start=original[0];client.request=original[2]
    with socket.socket() as probe:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    test_base=f'http://127.0.0.1:{port}'
    addon.preferences=lambda context:SimpleNamespace(runtime_root=str(ROOT),port=port)
    assert bpy.ops.toyxyz_motion_ai_tool.generate()=={'FINISHED'}
    owned=addon._launched_app[1];deadline=time.monotonic()+20
    while not sent:
        addon.timer()
        if time.monotonic()>deadline:raise TimeoutError(client.state['message'])
        time.sleep(.05)
    assert client.state['connected'] and len(sent)==1 and sent[0][0]=='submit'
    info=client.request(test_base,'/health');assert info['active_job'] is None and not info['jobs']
    assert owned.poll() is None and info['pid']==owned.pid
    report['checks'].append('With no app running on an isolated port, Generate launches the actual hidden companion and completes its lifetime handshake before one intercepted submit; no GPU model or user job is touched')
    report['status']='passed'
except BaseException as exc:
    report.update(status='failed',error_type=type(exc).__name__,error=str(exc));raise
finally:
    client.stop()
    if owned is not None and owned.poll() is None:
        try:original[2](test_base,'/shutdown',{});owned.wait(timeout=10)
        except Exception:
            if owned.poll() is None:owned.terminate();owned.wait(timeout=10)
    client.start,client.send,client.request,addon.preferences=original
    (ROOT/'results/blender_bridge'/('generate_auto_connect_installed.json' if installed else 'generate_auto_connect.json')).write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
