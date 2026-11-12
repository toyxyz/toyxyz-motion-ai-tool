"""Embedded motion samples, evaluated through unkeyed native bone constraints.

The armature's Action always belongs to the user. No generated FCurves, drivers,
helper objects, or extra armatures are created.
"""
from contextlib import contextmanager
import json
import math
import bpy
from bpy.app.handlers import persistent
from mathutils import Matrix,Quaternion,Vector
from . import rig

CACHE='toyxyz_motion_cache'
ENABLED='toyxyz_motion_preview'
ROTATION='toyxyz_motion_ai_tool · Motion Rotation'
LOCATION='toyxyz_motion_ai_tool · Motion Root'
_loaded={}
_suspended=set()


def managed(constraint):return constraint.name in (ROTATION,LOCATION)


def constraints(obj,create=False):
    found=[]
    for name in rig.NAMES:
        bone=obj.pose.bones[name];constraint=bone.constraints.get(ROTATION)
        if constraint is None and create:
            constraint=bone.constraints.new('LIMIT_ROTATION');constraint.name=ROTATION
            constraint.owner_space='LOCAL';constraint.euler_order='XYZ'
            constraint.use_limit_x=constraint.use_limit_y=constraint.use_limit_z=True
        if constraint:found.append(constraint)
    bone=obj.pose.bones[rig.NAMES[0]];constraint=bone.constraints.get(LOCATION)
    if constraint is None and create:
        constraint=bone.constraints.new('LIMIT_LOCATION');constraint.name=LOCATION;constraint.owner_space='LOCAL'
        for axis in 'xyz':setattr(constraint,'use_min_'+axis,True);setattr(constraint,'use_max_'+axis,True)
    if constraint:found.append(constraint)
    return found


def clip(obj):
    text=obj.get(CACHE)
    if not isinstance(text,bpy.types.Text):return None
    key=text.as_pointer()
    if key not in _loaded:
        value=json.loads(text.as_string())
        if value.get('version')!=1 or value.get('joint_names')!=rig.NAMES:raise ValueError('Unsupported embedded motion data.')
        _loaded[key]=value
    return _loaded[key]


def enabled(obj):return bool(obj.get(CACHE) and obj.get(ENABLED,False))


def update_rig(scene,obj):
    if not obj.get(CACHE):return
    value=clip(obj)
    frame=scene.frame_current+scene.frame_subframe
    active=enabled(obj) and obj.as_pointer() not in _suspended and value['start']<=frame<value['end']
    items=constraints(obj,create=True)
    if not active:
        for constraint in items:
            if constraint.influence:constraint.influence=0
        return
    sample=max(0,min(len(value['rotations'])-1,(frame-value['start'])*value['fps']/value.get('scene_fps',value['fps'])))
    a=int(sample);b=min(a+1,len(value['rotations'])-1);alpha=sample-a
    for index,name in enumerate(rig.NAMES):
        rotation=Quaternion(value['rotations'][a][index]).slerp(Quaternion(value['rotations'][b][index]),alpha).to_euler('XYZ')
        constraint=obj.pose.bones[name].constraints[ROTATION]
        for axis,angle in zip('xyz',rotation):
            if getattr(constraint,'min_'+axis)!=angle:setattr(constraint,'min_'+axis,angle)
            if getattr(constraint,'max_'+axis)!=angle:setattr(constraint,'max_'+axis,angle)
        if constraint.influence!=1:constraint.influence=1
    location=Vector(value['locations'][a]).lerp(Vector(value['locations'][b]),alpha)
    constraint=obj.pose.bones[rig.NAMES[0]].constraints[LOCATION]
    for axis,position in zip('xyz',location):
        if getattr(constraint,'min_'+axis)!=position:setattr(constraint,'min_'+axis,position)
        if getattr(constraint,'max_'+axis)!=position:setattr(constraint,'max_'+axis,position)
    if constraint.influence!=1:constraint.influence=1


def store(context,obj,value):
    # Serialize before replacing an existing clip so malformed data cannot detach it.
    payload=json.dumps(value,allow_nan=False,separators=(',',':'))
    text=bpy.data.texts.new('toyxyz_motion_ai_tool_Motion_Data');text.use_fake_user=False;text.write(payload)
    old=obj.get(CACHE);obj[CACHE]=text;obj[ENABLED]=True;_loaded[text.as_pointer()]=value
    if isinstance(old,bpy.types.Text):
        _loaded.pop(old.as_pointer(),None)
        if old.users==0 and not old.use_fake_user:bpy.data.texts.remove(old)
    update_rig(context.scene,obj)
    context.scene.frame_set(context.scene.frame_current,subframe=context.scene.frame_subframe)
    context.view_layer.update()


def apply(context,obj,data):
    rig.validate_rig(obj)
    if data.get('joint_names')!=rig.NAMES or data.get('status')!='succeeded':raise ValueError('Unsupported motion result.')
    fps=context.scene.render.fps/context.scene.render.fps_base
    if abs(fps-data['scene_fps'])>.001:raise ValueError('Scene FPS changed after submission. Restore it before applying the result.')
    rotations=data['local_rotations'];roots=data['root_positions']
    if len(roots)<2 or len(roots)!=len(rotations):raise ValueError('Invalid result frame count.')
    if data['end']<=data['start'] or not math.isfinite(data['fps']) or data['fps']<=0:raise ValueError('Invalid motion timing.')
    values=[];locations=[]
    for local,root in zip(rotations,roots):
        bases=rig.bases(obj,rig.desired_matrices(obj,local,root))
        values.append([list(matrix.to_quaternion()) for matrix in bases]);locations.append(list(bases[0].translation))
    migrate(context,obj)
    store(context,obj,dict(version=1,joint_names=rig.NAMES,start=data['start'],end=data['end'],fps=data['fps'],scene_fps=data['scene_fps'],
                           rotations=values,locations=locations,engine=data['engine'],job_id=data.get('job_id','')))
    obj['toyxyz_job_id']=data.get('job_id','')
    rig.consolidate_results(context,obj)
    return obj


def set_enabled(context,obj,value):
    rig.validate_rig(obj);migrate(context,obj)
    if value and not obj.get(CACHE):raise ValueError('Generate and apply a motion first.')
    obj[ENABLED]=bool(value);update_rig(context.scene,obj)
    context.scene.frame_set(context.scene.frame_current,subframe=context.scene.frame_subframe);context.view_layer.update()


@contextmanager
def suspended(context,obj):
    key=obj.as_pointer();already=key in _suspended;_suspended.add(key)
    update_rig(context.scene,obj)
    try:yield
    finally:
        if not already:_suspended.discard(key)
        update_rig(context.scene,obj);context.view_layer.update()


def migrate(context,obj):
    """Convert a tool-owned legacy baked Action, then restore the user's Action."""
    action=obj.get(rig.GENERATED_ACTION)
    if not isinstance(action,bpy.types.Action):return
    source,source_slot=rig.pose_action(obj)
    if source==action:source=obj.get(rig.POSE_ACTION);source_slot=rig.action_slot(source,obj.get('toyxyz_pose_slot',0))
    slot=rig.action_slot(action,obj.get('toyxyz_generated_slot',0))
    found={}
    for layer in action.layers:
        for strip in layer.strips:
            if strip.type=='KEYFRAME':
                bag=strip.channelbag(slot) if slot else None
                if bag:found.update({(fc.data_path,fc.array_index):fc for fc in bag.fcurves})
    paths=[obj.pose.bones[name].path_from_id('rotation_quaternion') for name in rig.NAMES]
    root_path=obj.pose.bones[rig.NAMES[0]].path_from_id('location')
    times=[point.co.x for (path,index),fc in found.items() if path in paths for point in fc.keyframe_points]
    cached=None
    if times and all((path,i) in found for path in paths for i in range(4)):
        start=math.floor(min(times));end=math.ceil(max(times))+1
        cached=dict(version=1,joint_names=rig.NAMES,start=start,end=end,fps=context.scene.render.fps/context.scene.render.fps_base,scene_fps=context.scene.render.fps/context.scene.render.fps_base,
                    rotations=[[[found[path,i].evaluate(frame) for i in range(4)] for path in paths] for frame in range(start,end)],
                    locations=[[found[root_path,i].evaluate(frame) if (root_path,i) in found else 0 for i in range(3)] for frame in range(start,end)],
                    engine='legacy',job_id=obj.get('toyxyz_job_id',''))
    was_active=obj.animation_data and obj.animation_data.action==action
    if was_active:
        rig.assign_action(obj,source,source_slot)
        if rig.POSE_BASE in obj:rig.restore_pose_state(obj,json.loads(obj[rig.POSE_BASE]))
    del obj[rig.GENERATED_ACTION]
    if 'toyxyz_generated_slot' in obj:del obj['toyxyz_generated_slot']
    if action.get('toyxyz_generated_for')==obj.get('toyxyz_uuid') and action.users==0 and not action.use_fake_user:bpy.data.actions.remove(action)
    if cached and not obj.get(CACHE):
        store(context,obj,cached);obj[ENABLED]=bool(was_active);update_rig(context.scene,obj)


@persistent
def on_frame_pre(scene,depsgraph=None):
    for obj in scene.objects:
        if obj.type=='ARMATURE' and obj.get(CACHE):update_rig(scene,obj)


@persistent
def on_load(_):
    _loaded.clear();_suspended.clear()
    for obj in bpy.context.scene.objects:
        if obj.type=='ARMATURE' and obj.get('toyxyz_soma'):migrate(bpy.context,obj)
    on_frame_pre(bpy.context.scene)


def register():
    if on_frame_pre not in bpy.app.handlers.frame_change_pre:bpy.app.handlers.frame_change_pre.append(on_frame_pre)
    if on_load not in bpy.app.handlers.load_post:bpy.app.handlers.load_post.append(on_load)
    for handlers in (bpy.app.handlers.undo_post,bpy.app.handlers.redo_post):
        if refresh not in handlers:handlers.append(refresh)
    # Addon registration runs in Blender's restricted context; defer scene access.
    if not bpy.app.timers.is_registered(initialize):bpy.app.timers.register(initialize,first_interval=0)


def initialize():
    on_load(None)
    return None


@persistent
def refresh(_):
    _loaded.clear();_suspended.clear();on_frame_pre(bpy.context.scene)


def unregister():
    if bpy.app.timers.is_registered(initialize):bpy.app.timers.unregister(initialize)
    for handlers,callback in ((bpy.app.handlers.frame_change_pre,on_frame_pre),(bpy.app.handlers.load_post,on_load)):
        if callback in handlers:handlers.remove(callback)
    for handlers in (bpy.app.handlers.undo_post,bpy.app.handlers.redo_post):
        if refresh in handlers:handlers.remove(refresh)
    for obj in bpy.data.objects:
        if obj.type=='ARMATURE' and obj.get(CACHE):
            for constraint in constraints(obj):constraint.influence=0
    _loaded.clear();_suspended.clear()
