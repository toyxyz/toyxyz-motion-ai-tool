"""Regressions for copied rigs, stale results, failed edits and FBX action ranges."""
from pathlib import Path
import json
import sys
import bpy
import addon_utils
from mathutils import Matrix
from tempfile import TemporaryDirectory
from unittest.mock import patch

if '--installed' not in sys.argv:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'addons'))
addon_utils.enable('toyxyz_motion_ai_tool', default_set=False)
import toyxyz_motion_ai_tool as addon
from toyxyz_motion_ai_tool import agent_bridge, client, control_layers, control_rig, continuity, final_motion, keyframes, nla_motion, rig, rig_store, timeline

records = []

def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable('toyxyz_motion_ai_tool', default_set=False)
    scene=bpy.context.scene
    scene.render.fps=30
    assert bpy.ops.toyxyz_motion_ai_tool.add_soma()=={'FINISHED'}
    return scene,rig_store.settings(scene)

scene,a=fresh()
first=a.rig
bpy.ops.object.mode_set(mode="OBJECT")
assert bpy.ops.object.duplicate()=={'FINISHED'}
second=bpy.context.object
rig_store.ensure(scene)
rig_store.select(scene,second,bpy.context)
uid=second.get('toyxyz_uuid')
records.append(dict(check='duplicate_actor_identity', duplicate=second.name, original=first.name,
                    same_id=uid==first.get('toyxyz_uuid'), routes_to=rig_store.job(scene,uid).rig.name))

scene,a=fresh()
original_uid=a.scene_uid
original_actor=a.rig
block=a.blocks[0]
timeline.set_range(block,1,31)
scene.name='A Original'
assert bpy.ops.scene.new(type='FULL_COPY')=={'FINISHED'}
copy_scene=bpy.context.scene
copy_scene.name='Z Full Copy'
rig_store.ensure(copy_scene)
copied=rig_store.settings(copy_scene)
assert copied.rig!=original_actor
data=addon.request_data(bpy.context,include_history=False)
ident=[list(map(list,Matrix.Identity(3))) for _ in rig.NAMES]
result=dict(status='succeeded',engine='ardy',job_id='audit-scene-copy',joint_names=rig.NAMES,start=1,end=31,
            fps=30,scene_fps=30,local_rotations=[ident]*30,root_positions=[(0,1.,0)]*30,blocks=data['blocks'])
client.state.update(scene_uid=copied.scene_uid,input_uuid=copied.rig.get('toyxyz_uuid'),result=result,
                    job_id=result['job_id'],job_status='succeeded',auto_apply_pending=True,auto_apply_error=False)
addon.auto_apply()
records.append(dict(check='full_copy_auto_apply', scene_same_id=copied.scene_uid==original_uid,
                    rig_same_id=copied.rig.get('toyxyz_uuid')==original_actor.get('toyxyz_uuid'),
                    original_applied=a.last_applied_job==result['job_id'],
                    copy_applied=copied.last_applied_job==result['job_id'], message=client.state['message']))

scene,a=fresh()
block=a.blocks[0]
timeline.set_range(block,1,31)
data=addon.request_data(bpy.context,include_history=False)
block.enabled=False
result.update(job_id='audit-disabled-block',blocks=data['blocks'])
client.state.update(scene_uid=a.scene_uid,input_uuid=a.rig.get('toyxyz_uuid'),result=result,
                    job_id=result['job_id'],job_status='succeeded',auto_apply_pending=True,auto_apply_error=False)
accepted=addon.prepare_result(bpy.context) is not None
addon.auto_apply()
tracks=[(strip.name,strip.mute) for track in a.rig.animation_data.nla_tracks for strip in track.strips] if a.rig.animation_data else []
records.append(dict(check='disabled_during_generation',accepted=accepted,has_result=block.has_result,strips=tracks,message=client.state['message']))

scene,a=fresh()
actor=a.rig
actor.scale.x=0.
scene.frame_set(7)
failure=agent_bridge.dispatch(bpy.context,'pose.key',dict(frame=18,bones={'Head':{'rotation':[.97,0,.243,0]}},root_position=[0,0,1]))
records.append(dict(check='agent_failed_edit_partial', reply=failure, keyframes=list(keyframes.frames(actor,force=True)), frame=scene.frame_current))

scene,a=fresh()
actor=a.rig
hip=actor.pose.bones['Hips']
for frame,value in ((10,0.),(40,2.)):
    hip.location.x=value
    hip.keyframe_insert('location',frame=frame)
actor.animation_data.use_nla=False
actor.animation_data.action_influence=0.
scene.frame_set(10); start=tuple(hip.matrix.translation)
scene.frame_set(40); end=tuple(hip.matrix.translation)
with TemporaryDirectory() as folder:
    path=Path(folder)/'active.fbx'
    bounds=final_motion.export_fbx(bpy.context,actor,str(path))
    assert bpy.ops.import_scene.fbx(filepath=str(path))=={'FINISHED'}
    imported=next(obj for obj in bpy.context.selected_objects if obj.type=='ARMATURE')
    span=imported.animation_data.action.frame_range
    first,last=round(span[0]),round(span[1])
    points=[]
    for frame in (first,last):
        scene.frame_set(frame)
        points.append(imported.matrix_world @ imported.pose.bones['Hips'].head)
    assert last-first==30 and abs((points[1]-points[0]).length-2)<.01
records.append(dict(check='fbx_active_action_without_nla', bounds=bounds,
                    evaluated_first=start,evaluated_last=end, influence=actor.animation_data.action_influence))
scene,a=fresh()
first=a.blocks[0]
timeline.set_range(first,1,31)
second=timeline.add(scene)
timeline.set_range(second,31,61)
timeline.selection_set(a,{first.uid,second.uid})
two=addon.request_data(bpy.context,include_history=False)
fixture=dict(result,job_id='audit-two-strips',start=1,end=61,local_rotations=[ident]*60,
             root_positions=[(0,1.,0)]*60,blocks=two['blocks'])
actor=a.rig
before=(len(bpy.data.actions),len(actor.animation_data.nla_tracks) if actor.animation_data else 0)
make=nla_motion.create_strip
count=0
def fail_second(*args,**kwargs):
    global count
    count+=1
    if count==2:
        raise RuntimeError('Injected failure before second strip creation.')
    return make(*args,**kwargs)
client.state.update(scene_uid=a.scene_uid,input_uuid=actor.get('toyxyz_uuid'),result=fixture,
                    job_id=fixture['job_id'],job_status='succeeded',auto_apply_pending=True,auto_apply_error=False)
with patch.object(nla_motion,'create_strip',side_effect=fail_second):
    addon.auto_apply()
records.append(dict(check='nla_partial_application_after_failure', before=before,
                    after=(len(bpy.data.actions),len(actor.animation_data.nla_tracks) if actor.animation_data else 0),
                    strips=[(strip.name,strip.frame_start,strip.frame_end) for track in actor.animation_data.nla_tracks for strip in track.strips] if actor.animation_data else [],
                    application_error=client.state['auto_apply_error'], message=client.state['message']))

scene,a=fresh()
block=a.blocks[0]
timeline.set_range(block,1,31)
data=addon.request_data(bpy.context,include_history=False)
fixture=dict(result,job_id='audit-late-after-cancel',blocks=data['blocks'])
client.state.update(scene_uid=a.scene_uid,input_uuid=a.rig.get('toyxyz_uuid'),result=None,
                    job_id=fixture['job_id'],job_status='running',auto_apply_pending=False,auto_apply_error=False)
with patch.object(client,'send') as send:
    outcome=bpy.ops.toyxyz_motion_ai_tool.app_control(command='cancel')
    assert send.call_args.args==('cancel',)
    client.events.put(('result',a.scene_uid,fixture))
    addon.timer()
records.append(dict(check='client_result_after_cancel',cancel_operator=list(outcome), block_applied=block.has_result,
                    applied_id=a.last_applied_job, message=client.state['message']))

scene,a=fresh()
current=bpy.context
metadata=agent_bridge.start(current)
try:
    directory=agent_bridge._session['path']
    request=directory/('a'*32+'.request.json')
    response=directory/('a'*32+'.response.json')
    payload=dict(protocol=1,session=metadata['id'],expires=__import__('time').time()+10,
                 command='actor.add',args={})
    agent_bridge.publish(request,payload)
    agent_bridge.tick(current)
    first_reply=json.loads(response.read_text(encoding='utf-8'))
    agent_bridge.publish(request,payload)
    agent_bridge.tick(current)
    second_reply=json.loads(response.read_text(encoding='utf-8'))
    records.append(dict(check='agent_repeat_request_id', first=first_reply['result']['name'],
                        second=second_reply['result']['name'], actors=len(rig_store.entries(scene))))
    agent_bridge.publish(request,dict(payload,args={'controls':True}))
    agent_bridge.tick(current)
    assert not json.loads(response.read_text(encoding='utf-8'))['ok']
    assert len(rig_store.entries(scene))==2
finally:
    agent_bridge.stop()

scene,a=fresh()
actor=a.rig
first=a.blocks[0]
timeline.set_range(first,1,31)
second=timeline.add(scene)
timeline.set_range(second,31,61)
timeline.selection_set(a,{first.uid})
first_request=addon.request_data(bpy.context,include_history=False)
rig.import_result(bpy.context,actor,dict(result,job_id='predecessor',blocks=first_request['blocks']))
timeline.selection_set(a,{second.uid})
submitted=addon.request_data(bpy.context)
assert submitted['previous_motion_context'] and submitted['poses'][0]['source']=='previous_motion_end'
old=submitted['poses'][0]['root']
clip=continuity.playback(actor).strips[0]
target=actor.pose.bones['Hips'].path_from_id('location')
curve=next(fc for fc in control_rig.action_curves(clip.action,clip.action_slot) if fc.data_path==target and fc.array_index==0)
for point in curve.keyframe_points:
    point.co.y+=.7
curve.update()
new=addon.request_data(bpy.context)['poses'][0]['root']
fixture=dict(result,job_id='audit-predecessor-edited',start=31,end=61,
             root_positions=[old]*30,blocks=submitted['blocks'])
client.state.update(scene_uid=a.scene_uid,input_uuid=actor.get('toyxyz_uuid'),result=fixture,
                    job_id=fixture['job_id'],job_status='succeeded',auto_apply_pending=True,auto_apply_error=False)
try:
    accepted=addon.prepare_result(bpy.context) is not None
except ValueError as exc:
    assert 'preceding motion' in str(exc), str(exc)
    accepted=False
addon.auto_apply()
positions=[]
for frame in range(27,37):
    scene.frame_set(frame)
    positions.append(actor.evaluated_get(bpy.context.evaluated_depsgraph_get()).pose.bones['Hips'].head.copy())
records.append(dict(check='previous_clip_edited_while_generating',old_predecessor_endpoint=old,new_predecessor_endpoint=new,
                    accepted=accepted,applied=second.has_result,hip_jump=max((b-a).length for a,b in zip(positions,positions[1:])), x_samples=[p.x for p in positions]))

# A genuine failure after one successful key write also rolls back an existing
# Action in place, including newly allocated channels and the current frame.
scene,a=fresh()
actor=a.rig
assert agent_bridge.dispatch(bpy.context,'pose.key',dict(frame=3,bones={'Head':{'rotation':[1,0,0,0]}}))['ok']
action,slot=rig.pose_action(actor)
def channels():
    return { (curve.data_path,curve.array_index):[(tuple(p.co),tuple(p.handle_left),tuple(p.handle_right)) for p in curve.keyframe_points]
            for curve in control_rig.action_curves(action,slot) }
old_channels=channels()
scene.frame_set(8)
saved=rig.pose_state(actor)
key_transform=control_rig.key_transform
def fail_hips(bone,*args):
    if bone.name=='Hips':raise RuntimeError('Injected pose key failure')
    return key_transform(bone,*args)
with patch.object(control_rig,'key_transform',side_effect=fail_hips):
    reply=agent_bridge.dispatch(bpy.context,'pose.key',dict(frame=12,bones={
        'LeftArm':{'rotation':[.97,0,.243,0]},'Head':{'rotation':[.97,0,.243,0]},'Hips':{'location':[0,0,0]}}))
assert not reply['ok'] and 'Injected pose' in reply['error'],reply
assert rig.pose_action(actor)==(action,slot) and channels()==old_channels
assert scene.frame_current==8 and rig.pose_state(actor)==saved

# A new result must not leave behind changes from absolute-key migration if
# native strip construction fails, even when the authored Action already exists.
actor=a.rig
action,slot=rig.pose_action(actor)
before=(set(bpy.data.actions),channels(),dict(action.items()),rig.pose_state(actor))
timeline.set_range(a.blocks[0],1,31)
submitted=addon.request_data(bpy.context,include_history=False)
with patch.object(nla_motion,'create_strip',side_effect=RuntimeError('Injected NLA failure')):
    try:
        rig.import_result(bpy.context,actor,dict(result,job_id='rollback-existing-action',blocks=submitted['blocks']))
    except RuntimeError as exc:
        assert 'Injected NLA failure' in str(exc)
    else:
        raise AssertionError('An injected NLA failure was ignored')
assert rig.pose_action(actor)==(action,slot)
assert before==(set(bpy.data.actions),channels(),dict(action.items()),rig.pose_state(actor))

# A late event retains its old submission token after generation starts again.
with patch.object(client,'commands',client.queue.Queue()):
    client.send('submit',{})
    old_token=client.submission_token
    client.send('submit',{})
    client.state.update(scene_uid=a.scene_uid,job_status='queued',result=None,cancel_requested=False)
    client.events.put(('result',a.scene_uid,result,old_token))
    addon.timer()
    assert client.state['job_status']=='queued' and client.state['result'] is None

# Duplicating a generated actor leaves its editable Action and playback
# independent while retaining the timing and Control Layer of the copy.
scene,a=fresh()
actor=a.rig
timeline.set_range(a.blocks[0],1,31)
submitted=addon.request_data(bpy.context,include_history=False)
rig.import_result(bpy.context,actor,dict(result,job_id='duplicate-generated',blocks=submitted['blocks']))
control_layers.add(bpy.context,a,4,23)
control_layers.deselect(bpy.context,a)
source_strip=continuity.playback(actor).strips[0]
source_layer=control_layers.rows(actor)[0][1]
assert bpy.ops.object.mode_set(mode='OBJECT')=={'FINISHED'}
assert bpy.ops.object.duplicate()=={'FINISHED'}
clone=bpy.context.object
rig_store.ensure(scene)
assert clone!=actor and clone['toyxyz_uuid']!=actor['toyxyz_uuid']
assert clone.animation_data.action!=actor.animation_data.action
for old,new in ((source_strip,continuity.playback(clone).strips[0]),(source_layer,control_layers.rows(clone)[0][1])):
    assert new.action!=old.action
    assert (new.frame_start,new.frame_end,new.mute,new.blend_type)==(old.frame_start,old.frame_end,old.mute,old.blend_type)

# Re-evaluating the unchanged predecessor must accept the request for all models.
for engine in ('ardy','kimodo','motionbricks'):
    scene,a=fresh()
    first=a.blocks[0]
    timeline.set_range(first,1,31)
    middle=timeline.add(scene)
    middle.engine=engine
    end=89 if engine=='motionbricks' else 91
    timeline.set_range(middle,31,end)
    last=timeline.add(scene)
    last.engine='ardy'
    timeline.set_range(last,end,end+30)
    for block,start in ((first,1),(last,end)):
        timeline.selection_set(a,{block.uid})
        submitted=addon.request_data(bpy.context,include_history=False)
        rig.import_result(bpy.context,a.rig,dict(result,job_id=f'neighbor-{start}',start=start,end=start+30,blocks=submitted['blocks']))
    timeline.selection_set(a,{middle.uid})
    submitted=addon.request_data(bpy.context)
    block=submitted['blocks'][0]
    assert block.get('inherited_pose_signature') and block.get('following_motion_signature'),engine
    if engine!='motionbricks':assert block.get('previous_motion_signature'),engine
    fixture=dict(result,job_id='neighbor-middle',engine=engine,start=31,end=end,blocks=submitted['blocks'],
                 next_motion_reference=submitted['next_motion_context']['reference'])
    client.state.update(scene_uid=a.scene_uid,input_uuid=a.rig['toyxyz_uuid'],result=fixture,
                        job_scene_session_uid=scene.session_uid,job_rig_session_uid=a.rig.session_uid,cancel_requested=False)
    scene.frame_set(53,subframe=.25)
    assert addon.prepare_result(bpy.context),engine
    assert scene.frame_current==53 and scene.frame_subframe==.25
    next_strip=continuity.playback(a.rig).strips[-1]
    path=a.rig.pose.bones['Hips'].path_from_id('location')
    curve=next(fc for fc in control_rig.action_curves(next_strip.action,next_strip.action_slot) if fc.data_path==path and fc.array_index==0)
    for point in curve.keyframe_points:point.co.y+=.25
    curve.update()
    try:
        addon.prepare_result(bpy.context)
    except ValueError as exc:
        assert 'following motion changed' in str(exc),(engine,str(exc))
    else:
        raise AssertionError(f'{engine} accepted edited following motion')

print(json.dumps(records,indent=2),flush=True)
checks={record['check']:record for record in records}
assert not checks['duplicate_actor_identity']['same_id']
assert checks['duplicate_actor_identity']['routes_to']==checks['duplicate_actor_identity']['duplicate']
copy=checks['full_copy_auto_apply']
assert not copy['scene_same_id'] and not copy['rig_same_id'] and not copy['original_applied'] and copy['copy_applied']
disabled=checks['disabled_during_generation']
assert not disabled['accepted'] and not disabled['has_result']
failed=checks['agent_failed_edit_partial']
assert not failed['reply']['ok'] and not failed['keyframes'] and failed['frame']==7
assert checks['fbx_active_action_without_nla']['bounds']==(10,40)
partial=checks['nla_partial_application_after_failure']
assert partial['before']==partial['after'] and not partial['strips'] and partial['application_error']
assert not checks['client_result_after_cancel']['block_applied']
retry=checks['agent_repeat_request_id']
assert retry['first']==retry['second'] and retry['actors']==2
previous=checks['previous_clip_edited_while_generating']
assert not previous['accepted'] and not previous['applied']
