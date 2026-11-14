"""Main-thread sequence orchestration across model changes and native NLA application."""
from . import rig_store
import time
import bpy
from . import client,timeline,keyframes,rig,curve_paths,pose_constraints,object_constraints,kimodo_context

CONNECT_TIMEOUT=60


def update_progress(value,stage):
    state=client.state;value=max(0,min(100,float(value)));state['job_progress']=value
    sequence=state.get('sequence')
    if sequence:
        value=100*(sequence['done_blocks']+sequence['current_blocks']*min(.99,value/100))/sequence['total_blocks']
    state.update(progress=min(99,value),progress_stage=stage)


def groups(blocks):
    result=[]
    for block in blocks:
        if not result or result[-1]['engine']!=block['engine']:
            result.append(dict(engine=block['engine'],blocks=[]))
        result[-1]['blocks'].append(dict(block))
    return result


def submit(context,group,*,include_following=True):
    from . import request_data
    s=rig_store.settings(context.scene)
    data=request_data(context,group['engine'],group['blocks'],include_following=include_following)
    if data['engine']=='ardy' and data['postprocess'] and 'ardy_full_block_join' in client.state.get('capabilities',[]):
        from . import ardy_transition,control_layers
        with control_layers.without_layers(context,s.rig,preserve_pose=True):
            join=ardy_transition.payload(context,s.rig,data['blocks'],data['poses'],data.get('previous_motion_context'))
        if join:
            data['ardy_join']=join
    if data.get('next_motion_context') and 'next_motion_context' not in client.state.get('capabilities',[]):
        raise ValueError('Restart the companion app to generate into the following motion.')
    if any(p.get('object_goal') for p in data['poses']) and 'object_constraints' not in client.state.get('capabilities',[]):
        raise ValueError('Restart the companion app to enable object constraints.')
    if any(p.get('root_heading') for p in data['poses']) and 'root_heading' not in client.state.get('capabilities',[]):
        raise ValueError('Restart the companion app to enable Root Heading.')
    if any(p.get('root_height') for p in data['poses']) and 'root_height' not in client.state.get('capabilities',[]):
        raise ValueError('Restart the companion app to enable Root Height.')
    if any(b.get('root_path',{}).get('start_index',0) for b in data['blocks']) and 'delayed_curve_start' not in client.state.get('capabilities',[]):
        raise ValueError('Restart the companion app to enable Curve Start (%).')
    client.state.update(scene_uid=s.scene_uid,input_uuid=s.rig['toyxyz_uuid'],view_layer=context.view_layer.name,job_status='queued',
                        job_scene_session_uid=context.scene.session_uid,job_rig_session_uid=s.rig.session_uid,
                        job_id='',result=None,applied_job=None,auto_apply_pending=False,auto_apply_error=False,
                        cancel_requested=False,message='Submitting job...')
    update_progress(0,'Submitting job...')
    client.send('submit',data)


def validate_blocks(scene,blocks):
    s=rig_store.settings(scene);live={b.uid:b for b in s.blocks}
    for source in blocks:
        block=live.get(source['uid'])
        if not block or not block.enabled or any(getattr(block,key)!=source[key] for key in ('start','end','engine','prompt')):
            raise ValueError('A sequence block changed. Select the remaining blocks and generate again.')
        if block.engine=='kimodo' and block.transition_frames!=source.get('requested_transition_frames',source.get('transition_frames',5)):
            raise ValueError('A transition overlap changed. Generate the selection again.')
        if 'constraint_types' in source and pose_constraints.signature(rig_store.settings(scene).rig,block.start,block.end)!=source['constraint_types']:
            raise ValueError('Pose constraint keys or types changed. Generate the selection again.')
        if ('object_constraint_definitions' in source and
                [list(m) for m in object_constraints.definitions(s,block.start,block.end)]!=source['object_constraint_definitions']):
            raise ValueError('Object constraint markers changed. Generate the selection again.')
        if not curve_paths.matches(scene,block,source):raise ValueError('A Path Curve changed. Generate the selection again.')


def connect_then_start(context):
    from . import request_data
    s=rig_store.settings(context.scene);obj=rig.validate_rig(s.rig)
    _,blocks=timeline.generation_blocks(context);blocks=curve_paths.attach(context,blocks);plan=groups(blocks);first=plan[0]
    # Validate the first request before beginning a connection; never submit it
    # until the client's health handshake has confirmed the companion app.
    request_data(context,first['engine'],first['blocks'],include_following=len(plan)==1)
    if bpy.ops.toyxyz_motion_ai_tool.launch_app()!={'FINISHED'}:raise ValueError('Could not start or connect to the companion app. Check External App Folder and logs/toyxyz_motion_ai_tool_app.log.')
    client.state.update(pending_connect=dict(scene_uid=s.scene_uid,rig_uuid=obj['toyxyz_uuid'],
                        scene_session_uid=context.scene.session_uid,rig_session_uid=obj.session_uid,
                        blocks=blocks,fps=timeline.fps(context.scene),started=time.monotonic()),
                        job_status='connecting',progress=0,progress_stage='Connecting',connection_error='',message='Starting app and connecting before generation...')


def advance_connection():
    state=client.state;pending=state.get('pending_connect')
    if not pending:return False
    try:
        if state['scene_uid']!=pending['scene_uid']:raise ValueError('The connected scene changed. Generate again in the desired scene.')
        if not state['connected']:
            if time.monotonic()-pending['started']<CONNECT_TIMEOUT:return False
            raise ValueError('Could not connect to the companion app within 60 seconds. Check External App Folder and logs/toyxyz_motion_ai_tool_app.log, then click Start.')
        scene=rig_store.scene_for_job(pending['scene_uid'],pending.get('scene_session_uid'))
        if scene is None:raise ValueError('The original scene was removed.')
        s=rig_store.job(scene,pending['rig_uuid'],pending.get('rig_session_uid'))
        if s is None:raise ValueError('The original SOMA rig was removed.')
        if abs(timeline.fps(scene)-pending['fps'])>.001:raise ValueError('The scene FPS changed. Generate again.')
        state['pending_connect']=None
        with rig_store.use(scene,s),bpy.context.temp_override(scene=scene,view_layer=scene.view_layers[0]):
            validate_blocks(scene,pending['blocks']);start(bpy.context,pending['blocks'])
    except Exception as exc:
        state.update(pending_connect=None,job_status='failed',connecting=False,progress=None,message=str(exc))
    return True


def start(context,blocks=None):
    s=rig_store.settings(context.scene)
    if s.scene_uid!=client.state['scene_uid']:raise ValueError('Connect this scene before generating.')
    if blocks is None:_,blocks=timeline.generation_blocks(context)
    else:validate_blocks(context.scene,blocks)
    blocks=curve_paths.attach(context,blocks)
    plan=groups(blocks)
    # Later MotionBricks groups inherit their predecessor only after it is applied.
    # Check key spacing/count now without evaluating an obsolete generated base.
    values=keyframes.frames(s.rig,force=True,model_only=True);fps=timeline.fps(context.scene)
    for index,group in enumerate(plan[1:],1):
        if group['engine']=='motionbricks':
            a=group['blocks'][0]['start'];b=group['blocks'][-1]['end']
            if object_constraints.definitions(s,a,b):
                raise ValueError('MotionBricks requires Full Body pose keys. Use Kimodo or ARDY for object constraints.')
            keys=[f for f in values if a<=f<b]
            inherited=not any(keyframes.model_frame_index(f,a,b,fps)==0 for f in keys)
            following=index==len(plan)-1 and kimodo_context.following_clip(s.rig,s,group['blocks'])
            keyframes.validate_motionbricks_times(keys,a,b,fps,inherited=inherited,following=bool(following))
    submit(context,plan[0],include_following=len(plan)==1)
    client.state.update(sequence=dict(pending=plan[1:],blocks=blocks,fps=fps,total=len(plan),
                        done_blocks=0,current_blocks=len(plan[0]['blocks']),total_blocks=len(blocks)),sequence_jobs=[])


def advance():
    state=client.state;sequence=state.get('sequence')
    if not sequence:return False
    if state['job_status'] in ('failed','cancelled') or state.get('auto_apply_error'):
        state['sequence']=None;return True
    if not state['connected'] or state['job_status']!='succeeded' or state.get('applied_job')!=state.get('job_id'):return False
    state['sequence_jobs'].append(dict(job_id=state['job_id'],engine=state['result']['engine'],blocks=state['result']['blocks']))
    sequence['done_blocks']+=sequence['current_blocks']
    state.update(progress=100*sequence['done_blocks']/sequence['total_blocks'],progress_stage='Applied')
    if not sequence['pending']:
        state['sequence']=None
        state.update(progress=100,progress_stage='Complete')
        if sequence['total']>1:state['message']='Selected motion blocks generated and applied.'
        return True
    try:
        scene=rig_store.scene_for_job(state['scene_uid'],state.get('job_scene_session_uid'))
        if scene is None:raise ValueError('The original scene was removed.')
        s=rig_store.job(scene,state['input_uuid'],state.get('job_rig_session_uid'))
        if s is None:raise ValueError('The original SOMA rig was removed.')
        if abs(timeline.fps(scene)-sequence['fps'])>.001:raise ValueError('Restore the submitted scene FPS.')
        # Existing generated clips from the previous model now supply the start
        # pose (and four MotionBricks context samples) through keyframes.targets.
        sequence['current_blocks']=len(sequence['pending'][0]['blocks'])
        with rig_store.use(scene,s),bpy.context.temp_override(scene=scene,view_layer=scene.view_layers[0]):
            validate_blocks(scene,sequence['blocks']);submit(bpy.context,sequence['pending'][0],include_following=len(sequence['pending'])==1)
        sequence['pending'].pop(0)
    except Exception as exc:
        state.update(sequence=None,job_status='failed',message='Sequence stopped: '+str(exc))
    return True
