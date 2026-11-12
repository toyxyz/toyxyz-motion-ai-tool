"""Native NLA generation blocks and results; no Python pose playback."""
from . import rig_store
from contextlib import contextmanager
import json
import math
import uuid
import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix,Quaternion,Vector
from . import rig,model_limits

OWNER='toyxyz_generated_for'
ENGINE='toyxyz_model'
REQUEST='toyxyz_request'
PROMPT='toyxyz_prompt'
MOVING_START='toyxyz_moving_start'
START_STRIP='Motion AI · Start Frame'
_busy=False
_bounds={}
_msg_owner=object()


def owned(obj,strip):
    return strip.action and strip.action.get(OWNER)==obj.get('toyxyz_uuid') and not strip.name.startswith(START_STRIP)


def strips(obj):
    animation=obj.animation_data if obj else None
    return [(track,strip) for track in animation.nla_tracks for strip in track.strips if owned(obj,strip)] if animation else []


def selected(obj):
    items=[(track,strip) for track,strip in strips(obj) if strip.select]
    active=next((item for item in items if item[1].active),None)
    if active is None and obj and obj.animation_data:
        active=next((item for item in items if item[0]==obj.animation_data.nla_tracks.active),None)
    return active or (items[-1] if items else None)


def mark(action,obj,engine,prompt='',request=False,uid=None):
    action[OWNER]=obj['toyxyz_uuid'];action[ENGINE]=engine;action[PROMPT]=prompt;action[REQUEST]=request
    action['toyxyz_block_uid']=uid or uuid.uuid4().hex


def has_keys(action):
    return any(fc.keyframe_points or fc.sampled_points for layer in action.layers for strip in layer.strips
               if strip.type=='KEYFRAME' for bag in strip.channelbags for fc in bag.fcurves)


def create_strip(obj,track,action,slot,start,end,name):
    strip=track.strips.new(name,math.floor(start),action)
    strip.action_slot=slot;strip.blend_type='REPLACE';strip.extrapolation='NOTHING' if action.get(REQUEST) else 'HOLD';strip.use_auto_blend=False
    strip.action_frame_start=action.frame_start if action.use_frame_range else start
    strip.action_frame_end=action.frame_end if action.use_frame_range else end
    strip.frame_start_raw=start;strip.frame_end_raw=end
    strip.scale=(end-start)/max(.001,(strip.action_frame_end-strip.action_frame_start)*strip.repeat)
    strip.frame_start_raw=start;strip.frame_end_raw=end;strip.select=True
    return strip


def add_request(context,obj,engine,start=None,end=None,prompt='A person walks forward.',name=None,uid=None):
    rig.validate_rig(obj);animation=obj.animation_data_create()
    fps=context.scene.render.fps/context.scene.render.fps_base
    start=context.scene.frame_current if start is None else start
    duration=model_limits.clamp(engine,fps,(end-start) if end is not None else 2*fps)
    action=bpy.data.actions.new('toyxyz_motion_ai_tool_Request_'+engine)
    slot=action.slots.new(id_type='OBJECT',name=obj.name)
    action.use_frame_range=True;action.frame_start=start;action.frame_end=start+duration
    mark(action,obj,engine,prompt,True,uid)
    for _,item in strips(obj):item.select=False
    track=animation.nla_tracks.new();track.name=(name or engine.title())+' · Request'
    strip=create_strip(obj,track,action,slot,start,start+duration,name or engine.title())
    animation.nla_tracks.active=track
    _bounds[strip.as_pointer()]=(strip.frame_start,strip.frame_end)
    return strip


def blocks(context,obj):
    active=selected(obj)
    if not active:raise ValueError('Select a Kimodo or MotionBricks block in the NLA Editor.')
    engine=active[1].action[ENGINE];result=[]
    for track,strip in strips(obj):
        if not strip.select or strip.action.get(ENGINE)!=engine:continue
        start=round(strip.frame_start);end=round(strip.frame_end)
        if abs(strip.frame_start-start)>.001 or abs(strip.frame_end-end)>.001:raise ValueError('Snap selected NLA blocks to whole frames before generating.')
        result.append(dict(start=start,end=end,prompt=strip.action.get(PROMPT,''),name=strip.name,uid=strip.action.get('toyxyz_block_uid','')))
    return engine,sorted(result,key=lambda block:block['start'])


def generated_enabled(obj):return bool(obj and obj.get('toyxyz_nla_preview',False))


def preview(context,obj,generated):
    from . import unified
    rig.validate_rig(obj);animation=obj.animation_data_create()
    if animation.use_tweak_mode:raise ValueError('Exit NLA Tweak Mode before changing playback mode.')
    if generated:
        unified.enable(context,obj)
    else:
        obj[unified.ENABLED]=False
        from . import continuity
        track=continuity.playback(obj)
        if track:track.is_solo=False
        # Use Blender's native evaluation switch; never rewrite strip mute choices.
        animation.use_nla=False
        animation.action_influence=float(obj.get('toyxyz_author_influence',1))
    obj['toyxyz_nla_preview']=bool(generated)
    context.scene.frame_set(context.scene.frame_current,subframe=context.scene.frame_subframe);context.view_layer.update()


@contextmanager
def authoring(context,obj):
    from . import unified,continuity
    animation=obj.animation_data
    if not animation:yield;return
    if animation.use_tweak_mode:raise ValueError('Exit NLA Tweak Mode before generating from native authoring keys.')
    use_nla=animation.use_nla;influence=animation.action_influence;blend=animation.action_blend_type
    track=continuity.playback(obj);solo=track.is_solo if track else False
    with unified.suspend():
        try:
            if track:track.is_solo=False
            animation.use_nla=bool(obj.get(unified.ENABLED) and track)
            animation.action_blend_type='COMBINE' if animation.action and animation.action.get(unified.OFFSETS) else 'REPLACE'
            animation.action_influence=float(obj.get('toyxyz_author_influence',1))
            yield
        finally:
            if track:track.is_solo=solo
            animation.use_nla=use_nla;animation.action_influence=influence;animation.action_blend_type=blend
            context.scene.frame_set(context.scene.frame_current,subframe=context.scene.frame_subframe);context.view_layer.update()


def remove_cache(obj):
    from . import motion_cache
    for bone in obj.pose.bones:
        for constraint in list(bone.constraints):
            if motion_cache.managed(constraint):bone.constraints.remove(constraint)
    text=obj.get(motion_cache.CACHE)
    if motion_cache.CACHE in obj:del obj[motion_cache.CACHE]
    if motion_cache.ENABLED in obj:del obj[motion_cache.ENABLED]
    if isinstance(text,bpy.types.Text) and text.users==0 and not text.use_fake_user:bpy.data.texts.remove(text)
    motion_cache._loaded.clear()


def sample_result(data,frame):
    roots=data['root_positions'];rotations=data['local_rotations']
    count=len(roots);rate=data['fps']/data['scene_fps']
    sample=min(count-1,max(0,(frame-data['start'])*rate))
    a=int(sample);b=min(a+1,count-1);alpha=sample-a
    next_root,next_rotations=roots[b],rotations[b]
    following=data.get('next_motion_pose')
    if following and a==count-1:
        last_time=data['start']+(count-1)/rate
        alpha=min(1.,max(0.,(frame-last_time)/(data['end']-last_time)))
        next_root,next_rotations=following['root'],following['local_rotations']
    root=Vector(roots[a]).lerp(Vector(next_root),alpha)
    local=[Matrix(left).to_quaternion().slerp(Matrix(right).to_quaternion(),alpha).to_matrix()
           for left,right in zip(rotations[a],next_rotations)]
    return root,local


def add_linear_curve(bag,path,index,coordinates):
    curve=bag.fcurves.new(data_path=path,index=index)
    curve.keyframe_points.add(len(coordinates)//2)
    curve.keyframe_points.foreach_set('co',coordinates)
    for point in curve.keyframe_points:point.interpolation='LINEAR'
    curve.update()


def bake_action(obj,data,block,authored=None):
    from . import unified,control_rig
    if control_rig.enabled(obj):
        return control_rig.bake_action(obj,data,block,authored)
    corrections=unified.correction_curves(obj);authored=unified.full_body_overrides(obj,block,authored or {})
    if block.get('root_path'):
        # The curve controls horizontal placement. Do not snap the generated root
        # back to an old authored location key; the correction layer still stays
        # intact and is removed from the new base by unified.components.
        root_path=obj.pose.bones[rig.NAMES[0]].path_from_id('location')
        curve_start=block['start']+block['root_path'].get('start_index',0)*data['scene_fps']/data['fps']
        authored={frame:{path:value for path,value in channels.items() if path!=root_path or frame<curve_start} for frame,channels in authored.items()}
    start,end=block['start'],block['end']
    # The base contains generated bone motion only; user object/custom channels
    # remain on the active correction Action and must not be copied twice.
    action=bpy.data.actions.new('toyxyz_motion_ai_tool')
    action.name='toyxyz_motion_ai_tool_'+data['engine']+'_'+block.get('name','Motion');action.use_fake_user=False
    slot=action.slots.new(id_type='OBJECT',name=obj.name)
    layer=action.layers.new('Generated Motion');strip=layer.strips.new(type='KEYFRAME')
    bag=strip.channelbag(slot,ensure=True)
    modes={name:obj.pose.bones[name].rotation_mode for name in rig.GENERATED_NAMES}
    channels={name:'rotation_quaternion' if mode=='QUATERNION' else 'rotation_axis_angle' if mode=='AXIS_ANGLE' else 'rotation_euler' for name,mode in modes.items()}
    values={(name,index):[] for name in modes for index in range(3 if channels[name]=='rotation_euler' else 4)};locations=[[],[],[]];previous={}
    for frame in range(start,end+1):
        root,local=sample_result(data,frame)
        matrices=rig.bases(obj,rig.desired_matrices(obj,local,root))
        for name,matrix in zip(rig.NAMES,matrices):
            if name not in modes:continue
            q=matrix.to_quaternion()
            if modes[name]=='QUATERNION':
                if name in previous and previous[name].dot(q)<0:q.negate()
                previous[name]=q.copy();components=q
            elif modes[name]=='AXIS_ANGLE':
                axis,angle=q.to_axis_angle();components=(angle,*axis)
            else:
                components=q.to_euler(modes[name],previous[name]) if name in previous else q.to_euler(modes[name])
                previous[name]=components.copy()
            components=unified.components(obj,name,channels[name],frame,components,corrections,authored)
            for axis,component in enumerate(components):values[name,axis].extend((frame,component))
        location=unified.components(obj,rig.NAMES[0],'location',frame,matrices[0].translation,corrections,authored)
        for axis in range(3):locations[axis].extend((frame,location[axis]))
    # At shared boundaries both adjacent strips carry the same next-frame sample.
    for (name,index),coordinates in values.items():
        add_linear_curve(bag,obj.pose.bones[name].path_from_id(channels[name]),index,coordinates)
    for axis,coordinates in enumerate(locations):
        add_linear_curve(bag,obj.pose.bones[rig.NAMES[0]].path_from_id('location'),axis,coordinates)
    action.use_frame_range=True;action.frame_start=start;action.frame_end=end
    mark(action,obj,data['engine'],block.get('prompt',''),False,block.get('uid'))
    action['toyxyz_job_id']=data.get('job_id','')
    action['toyxyz_rotation_modes']=json.dumps(modes)
    return action,slot


def partition_blocks(data,fps):
    result=[];low,high=model_limits.frames(data['engine'],fps)
    for block in data.get('blocks') or [dict(start=data['start'],end=data['end'],name='Motion',prompt='')]:
        length=block['end']-block['start'];count=max(1,math.ceil(length/high))
        base,extra=divmod(length,count);start=block['start']
        for index in range(count):
            size=base+(index<extra);item=dict(block,start=start,end=start+size)
            if count>1:item['name']=block.get('name','Motion')+f' {index+1}'
            result.append(item);start+=size
    return result


def apply(context,obj,data):
    from . import block_links,control_layers,scene_sampling
    with scene_sampling.scope(scene_sampling.SAMPLING,context.scene,True),block_links.transaction(context.scene),control_layers.without_layers(context,obj):
        result=_apply(context,obj,data)
        for block in block_links.blocks(context.scene).values():block_links.push_range(context.scene,block)
    scene_sampling.publish(context,obj)
    return result


@contextmanager
def apply_transaction(context,obj):
    from . import continuity,correction_bounds,keyframes,unified
    had_animation=obj.animation_data is not None
    animation=obj.animation_data_create()
    active_track=animation.nla_tracks.active
    source,slot=animation.action,animation.action_slot
    prior_tracks={t:(t.mute,t.is_solo) for t in animation.nla_tracks}
    prior_strips={s:(s.mute,s.select,s.action,s.action_slot) for t in prior_tracks for s in t.strips}
    fake_users={action:action.use_fake_user for _,_,action,_ in prior_strips.values() if action}
    prior_flags=(animation.use_nla,animation.action_influence,animation.action_blend_type)
    properties=(rig.POSE_BASE,continuity.TRACK,continuity.READY,unified.ENABLED,'toyxyz_nla_preview','toyxyz_author_influence')
    prior_properties={key:obj.get(key) for key in properties}
    pose=rig.pose_state(obj)
    actions=set(bpy.data.actions)
    backup=source.copy() if source and slot and not source.get(unified.OFFSETS) else None
    paths={curve.data_path for curve in keyframes.curves(obj)} if backup else set()
    source_properties={key:source.get(key) for key in (unified.OFFSETS,unified.BACKUP)} if source else {}
    try:
        with correction_bounds.replace_on_success(obj):
            yield animation
    except BaseException:
        for track in list(animation.nla_tracks):
            if track not in prior_tracks:animation.nla_tracks.remove(track)
        for track,(mute,solo) in prior_tracks.items():track.mute=mute;track.is_solo=solo
        for strip,(mute,select,action,action_slot) in prior_strips.items():
            strip.mute=mute;strip.select=select
            if strip.action!=action:
                strip.action=action
                if action_slot:strip.action_slot=action_slot
        for action,value in fake_users.items():action.use_fake_user=value
        for key,value in prior_properties.items():
            if value is None:
                if key in obj:del obj[key]
            else:obj[key]=value
        if source:
            if backup:unified.restore_keyframes(source,slot,backup,paths)
            for key,value in source_properties.items():
                if value is None:
                    if key in source:del source[key]
                else:source[key]=value
        if had_animation:
            rig.assign_action(obj,source,slot)
            animation.use_nla,animation.action_influence,animation.action_blend_type=prior_flags
            animation.nla_tracks.active=active_track
        else:obj.animation_data_clear()
        for action in set(bpy.data.actions)-actions:
            if action!=backup and action.users==int(action.use_fake_user):bpy.data.actions.remove(action)
        keyframes.clear()
        context.scene.frame_set(context.scene.frame_current,subframe=context.scene.frame_subframe)
        rig.restore_pose_state(obj,pose,only_changed=True)
        context.view_layer.update()
        raise
    finally:
        if backup:bpy.data.actions.remove(backup)


def _apply(context,obj,data):
    rig.validate_rig(obj)
    if obj.animation_data and obj.animation_data.use_tweak_mode:raise ValueError('Exit NLA Tweak Mode before applying a generated result.')
    if data.get('status')!='succeeded' or data.get('joint_names')!=rig.NAMES:raise ValueError('Unsupported motion result.')
    fps=context.scene.render.fps/context.scene.render.fps_base
    if abs(fps-data['scene_fps'])>.001:raise ValueError('Restore the original scene FPS before applying the result.')
    if len(data['root_positions'])<(1 if data['engine']=='ardy' else 2) or len(data['root_positions'])!=len(data['local_rotations']):raise ValueError('Invalid result frame count.')
    source_blocks=partition_blocks(data,fps)
    from . import unified,continuity,correction_bounds,control_layers
    with apply_transaction(context,obj) as animation:
        if rig.POSE_BASE not in obj and not any(not strip.action.get(REQUEST) for _,strip in strips(obj)):
            obj[rig.POSE_BASE]=json.dumps(rig.pose_state(obj))
        unified.enable(context,obj)
        correction_bounds.sync(context.scene,obj,first_frame=source_blocks[0]['start'])
        authored=unified.capture(context,obj,[(block['start'],block['end']) for block in source_blocks])
        actions=[]
        for block in source_blocks:
            action,slot=bake_action(obj,data,block,authored)
            if data.get('moving_start') and block['start']==data['start']:action[MOVING_START]=True
            actions.append((block,action,slot))
        for _,strip in strips(obj):strip.select=False
        track=control_layers.new_lower_track(obj)
        track.name=data['engine'].title()+' · '+str(data.get('job_id','Generation'))[:12]
        for block,action,slot in actions:
            duration=model_limits.clamp(data['engine'],fps,block['end']-block['start'])
            create_strip(obj,track,action,slot,block['start'],block['start']+duration,block.get('name','Motion'))
        continuity.activate(context.scene,obj,track)
        unified.enable(context,obj)
    remove_cache(obj)
    animation.nla_tracks.active=track
    # Empty request strips are placeholders only; completed motion replaces them.
    uids={block.get('uid') for block in source_blocks if block.get('uid')}
    for old_track,strip in list(strips(obj)):
        if strip.action.get(REQUEST) and strip.action.get('toyxyz_block_uid') in uids and not has_keys(strip.action):
            action=strip.action;old_track.strips.remove(strip)
            if not old_track.strips:animation.nla_tracks.remove(old_track)
            if action.users==0:bpy.data.actions.remove(action)
    enforce(context.scene)
    rig.consolidate_results(context,obj)
    continuity.cleanup(obj)
    return obj


def enforce(scene):
    global _busy
    if _busy:return
    _busy=True
    try:
        fps=scene.render.fps/scene.render.fps_base
        for obj in scene.objects:
            if obj.type!='ARMATURE' or not obj.get('toyxyz_soma') or not obj.animation_data or obj.animation_data.use_tweak_mode:continue
            data=rig_store.for_rig(scene,obj) or rig_store.settings(scene)
            linked_uids={b.uid for b in data.blocks if b.uid}
            for track in obj.animation_data.nla_tracks:
                previous_end=None
                for strip in track.strips:
                    if not owned(obj,strip) or strip.action.get(ENGINE) not in model_limits.LIMITS:
                        previous_end=strip.frame_end;continue
                    if strip.action.get('toyxyz_block_uid') in linked_uids:
                        previous_end=strip.frame_end;continue
                    start,end=strip.frame_start,strip.frame_end;duration=end-start
                    limited=model_limits.clamp(strip.action[ENGINE],fps,duration)
                    old=_bounds.get(strip.as_pointer())
                    overlap=previous_end is not None and start<previous_end-.0001
                    if abs(duration-limited)>.0001 or overlap:
                        if old and abs(end-old[1])<.001 and abs(start-old[0])>.001:start=end-limited
                        if previous_end is not None:start=max(start,previous_end)
                        strip.scale=limited/max(.001,(strip.action_frame_end-strip.action_frame_start)*strip.repeat)
                        strip.frame_start_raw=start;strip.frame_end_raw=start+limited
                    previous_end=strip.frame_end
                    _bounds[strip.as_pointer()]=(strip.frame_start,strip.frame_end)
    finally:_busy=False


@persistent
def on_edit(scene,depsgraph=None):
    # No sample decoding or bone writes: during playback NLA owns evaluation entirely.
    from . import block_links
    if block_links.busy() or any(window.screen.is_animation_playing for window in bpy.context.window_manager.windows):return
    enforce(scene);rig_store.sync(scene)


def on_rna_edit():
    from . import block_links
    if bpy.context.scene and not block_links.busy():enforce(bpy.context.scene);rig_store.sync(bpy.context.scene)


def subscribe():
    bpy.msgbus.clear_by_owner(_msg_owner)
    for property in ('frame_start','frame_end','scale','repeat','action_frame_start','action_frame_end'):
        bpy.msgbus.subscribe_rna(key=(bpy.types.NlaStrip,property),owner=_msg_owner,args=(),notify=on_rna_edit,options={'PERSISTENT'})


@persistent
def on_load(_):
    _bounds.clear();subscribe()
    if not bpy.app.timers.is_registered(initialize):bpy.app.timers.register(initialize,first_interval=0)


def initialize():
    from . import motion_cache,timeline
    timeline.convert_editors()
    scene=bpy.context.scene
    for obj in list(scene.objects):
        if obj.type!='ARMATURE' or not obj.get('toyxyz_soma'):continue
        if obj.get(rig.GENERATED_ACTION):motion_cache.migrate(bpy.context,obj)
        text=obj.get(motion_cache.CACHE)
        if isinstance(text,bpy.types.Text):
            value=json.loads(text.as_string());was_enabled=bool(obj.get(motion_cache.ENABLED))
            engine=value.get('engine','kimodo')
            if engine not in model_limits.LIMITS:engine=rig_store.settings(scene).engine
            # Decode the former local-basis cache once. Playback thereafter is native NLA.
            roots=[];rotations=[]
            for quaternions,location in zip(value['rotations'],value['locations']):
                # Restore armature-space matrices without changing any user channels.
                matrices=[]
                for index,name in enumerate(rig.NAMES):
                    bone=obj.data.bones[name];base=Quaternion(quaternions[index]).to_matrix().to_4x4()
                    if index==0:base.translation=location;matrix=bone.matrix_local@base
                    else:
                        parent=rig.PARENTS[index]
                        matrix=matrices[parent]@obj.data.bones[rig.NAMES[parent]].matrix_local.inverted()@bone.matrix_local@base
                    matrices.append(matrix)
                globals=[rig.CI@matrix.to_3x3().normalized()@obj.data.bones[name].matrix_local.to_3x3().inverted()@rig.C for name,matrix in zip(rig.NAMES,matrices)]
                local=[globals[parent].transposed()@globals[index] if parent>=0 else globals[index] for index,parent in enumerate(rig.PARENTS)]
                rotations.append([list(map(list,matrix)) for matrix in local]);roots.append(list(rig.CI@matrices[0].translation/obj['toyxyz_units']))
            current_fps=scene.render.fps/scene.render.fps_base
            apply(bpy.context,obj,dict(status='succeeded',joint_names=rig.NAMES,engine=engine,start=value['start'],end=value['end'],
                                     fps=value['fps']*current_fps/value.get('scene_fps',current_fps),scene_fps=current_fps,
                                     root_positions=roots,local_rotations=rotations,job_id=value.get('job_id','Imported')))
            if not was_enabled:preview(bpy.context,obj,False)
    from . import block_links
    for saved_scene in bpy.data.scenes:
        from . import legacy_scene,continuity
        legacy_scene.restore(saved_scene);legacy_scene.restore_foot_curves(saved_scene)
        rig_store.ensure(saved_scene)
        for item in rig_store.entries(saved_scene):
            with rig_store.use(saved_scene,item.data):
                timeline.migrate_blocks(saved_scene);block_links.recover(saved_scene)
                with block_links.transaction(saved_scene):continuity.initialize(saved_scene)
    enforce(scene)
    from . import unified,control_layers
    for obj in scene.objects:
        if obj.type=='ARMATURE' and obj.get('toyxyz_soma') and obj.animation_data:
            from . import continuity
            if continuity.playback(obj) and not control_layers.editing(obj):unified.enable(bpy.context,obj)
    return None


def register():
    from . import unified
    unified.register()
    if on_edit not in bpy.app.handlers.depsgraph_update_post:bpy.app.handlers.depsgraph_update_post.append(on_edit)
    if on_load not in bpy.app.handlers.load_post:bpy.app.handlers.load_post.append(on_load)
    subscribe()
    if not bpy.app.timers.is_registered(initialize):bpy.app.timers.register(initialize,first_interval=0)


def unregister():
    from . import unified
    unified.unregister()
    if bpy.app.timers.is_registered(initialize):bpy.app.timers.unregister(initialize)
    bpy.msgbus.clear_by_owner(_msg_owner);_bounds.clear()
    for handlers,callback in ((bpy.app.handlers.depsgraph_update_post,on_edit),(bpy.app.handlers.load_post,on_load)):
        if callback in handlers:handlers.remove(callback)
