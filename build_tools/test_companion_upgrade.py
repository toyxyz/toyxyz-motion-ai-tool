"""Controlled upgrade state tests; no user process is stopped by this test."""
import json
from pathlib import Path
import sys
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'runtime'))
from entry import bootstrap
bootstrap('ardy')
import psutil
import ensure_companion_service as upgrade
old=dict(app='toyxyz_motion_ai_tool',protocol=1,instance='old',active_job=None,capabilities=[])
ready=dict(old,instance='new',capabilities=['blender_process_lifetime','object_constraints','next_motion_context','atomic_cancel'])
checks=[]
assert not upgrade.compatible(old)
assert not upgrade.compatible(dict(ready,capabilities=['blender_process_lifetime']))
assert not upgrade.compatible(dict(ready,capabilities=['blender_process_lifetime','object_constraints']))
assert not upgrade.compatible(dict(ready,capabilities=[*ready['capabilities'],'image_pose_capture']))
checks.append('Legacy services with image capture require an update even if Blender lifetime is already supported')
with patch.object(upgrade,'request',return_value=ready),patch.object(upgrade,'owned_listener') as owned:
    assert upgrade.ensure(8790)['restarted'] is False;owned.assert_not_called()
checks.append('Updated service is reused without stopping it')
with patch.object(upgrade,'request',return_value=dict(old,active_job='running')),patch.object(upgrade,'owned_listener') as owned:
    try:upgrade.ensure(8790);raise AssertionError('Busy service stopped')
    except RuntimeError as exc:assert 'Finish or cancel' in str(exc)
    owned.assert_not_called()
checks.append('Active generation prevents upgrade')
listener=Mock();listener.pid=991
fake=Mock();fake.status=psutil.CONN_LISTEN;fake.pid=991;fake.laddr=Mock(port=8790,ip='127.0.0.1')
listener.exe.return_value='C:/OtherInstallation/python.exe';listener.cmdline.return_value=['python.exe','other.py','bridge']
with patch.object(psutil,'net_connections',return_value=[fake]),patch.object(psutil,'Process',return_value=listener):
    try:upgrade.owned_listener(8790);raise AssertionError('Foreign service accepted')
    except RuntimeError as exc:assert 'another application or installation' in str(exc)
checks.append('Foreign installation is rejected before shutdown')
listener=Mock()
with patch.object(upgrade,'request',side_effect=[old,dict(old,instance='changed')]) as network,patch.object(upgrade,'owned_listener',return_value=listener):
    try:upgrade.ensure(8790);raise AssertionError('Changed service stopped')
    except RuntimeError as exc:assert 'state changed' in str(exc)
    assert all(call.args[1]!='/shutdown' for call in network.call_args_list)
checks.append('Instance change is detected before shutdown')
listener=Mock();child=Mock(pid=992);child.poll.return_value=None
with patch.object(upgrade,'request',side_effect=[old,old,{},OSError('stopped'),ready]) as network,patch.object(upgrade,'owned_listener',return_value=listener),patch.object(upgrade.subprocess,'Popen',return_value=child) as spawn:
    result=upgrade.ensure(8790)
    assert result['restarted'] and result['instance']=='new'
    listener.wait.assert_called_once_with(timeout=45);spawn.assert_called_once()
    assert sum(call.args[1]=='/shutdown' for call in network.call_args_list)==1
checks.append('Verified idle service shuts down gracefully, then updated service becomes ready')
out=ROOT/'results/capture_pose_removal/upgrade_tests.json'
out.write_text(json.dumps(dict(status='passed',checks=checks),indent=2),encoding='utf-8')
print(out.read_text(),flush=True)
