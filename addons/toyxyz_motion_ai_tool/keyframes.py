"""Pose targets derived from the input armature's native pose-authoring Action slot."""
import hashlib
import json
import math
import time
from . import rig,nla_motion,continuity,pose_constraints

_cache={}
_marker_cache={}
TRANSFORMS=('location','rotation_quaternion','rotation_euler','rotation_axis_angle','scale')


def clear():_cache.clear();_marker_cache.clear()


def curves(obj,include_modes=False,*,model_only=False):
    if obj is None or obj.type!='ARMATURE':return []
    action,slot=rig.pose_action(obj)
    if not action or action.get(nla_motion.OWNER):return []
    from . import control_rig
    names=set(control_rig.names(obj,model_only=model_only))
    paths={bone.path_from_id(channel) for bone in obj.pose.bones if bone.name in names for channel in TRANSFORMS}
    if include_modes:paths.update(control_rig.mode_paths(obj))
    found=[]
    if action.is_action_layered:
        if slot is None:return []
        for layer in action.layers:
            if getattr(layer,'mute',False):continue
            for strip in layer.strips:
                if strip.type!='KEYFRAME':continue
                bag=strip.channelbag(slot)
                if bag:found.extend(bag.fcurves)
    else:found.extend(getattr(action,'fcurves',()))
    # Empty channel reservations let native Auto Key create NLA correction keys.
    # They have no authored value and must not become zero-valued corrections.
    return [fc for fc in found if fc.data_path in paths and not fc.mute and fc.is_valid and (fc.keyframe_points or fc.sampled_points)]


def frames(obj,force=False,*,model_only=False):
    if obj is None:return ()
    key=(obj.as_pointer(),model_only);now=time.monotonic();cached=_cache.get(key)
    if not force and cached and now-cached[0]<.15:return cached[1]
    values=tuple(sorted({round(float(point.co.x),5) for fc in curves(obj,model_only=model_only) for point in fc.keyframe_points}))
    if not model_only:pose_constraints.sync(obj,force=force)
    _cache[key]=(now,values)
    return values


def value_signatures(obj,blocks):
    """Fingerprint keyed constraints without stepping Blender's timeline."""
    points=sorted((float(point.co.x),fc.data_path,fc.array_index,float(point.co.y))
                  for fc in curves(obj,include_modes=True,model_only=True) for point in fc.keyframe_points)
    return {b['uid']:hashlib.sha256(json.dumps([p for p in points if b['start']<=p[0]<b['end']],
                                             separators=(',',':')).encode()).hexdigest() for b in blocks}


def selected_frame(settings):
    values=frames(settings.rig)
    return min(values,key=lambda f:abs(f-settings.pose_key_frame)) if values else None


def markers(obj,force=False):
    """Native user key markers, including fingers, for display and editing."""
    if obj is None:return ()
    key=obj.as_pointer();now=time.monotonic();cached=_marker_cache.get(key)
    if not force and cached and now-cached[0]<.15:return cached[1]
    found={}
    for fc in curves(obj):
        for point in fc.keyframe_points:
            frame=round(float(point.co.x),5)
            found[frame]=found.get(frame,False) or point.select_control_point
    result=tuple(sorted(found.items()));_marker_cache[key]=(now,result)
    pose_constraints.sync(obj,force=force)
    return result


def model_frame_index(frame,start,end,fps):
    count=round((end-start)*30/fps)
    return max(0,min(count-1,round((frame-start)*30/fps)))


def validate_motionbricks_times(values,start,end,fps,inherited=False,following=False):
    if any(abs(f-round(f))>1e-4 for f in values):raise ValueError('Move SOMA pose keys to whole frames before generating.')
    times=sorted(set(values)|({start} if inherited else set()))
    if len(times)<(1 if following else 2):
        raise ValueError('MotionBricks needs two SOMA poses. Adjacent generated motion can supply the start or the destination.')
    for first,last in zip(times,times[1:]):
        if (last-first)*30/fps<1-1e-7 or model_frame_index(first,start,end,fps)==model_frame_index(last,start,end,fps):
            raise ValueError(f'MotionBricks: pose keys at frames {first:g} and {last:g} are too close. '
                             f'Space them at least {math.ceil(fps/30-1e-7)} scene frames apart (30 FPS model sampling).')


def inherited_pose(context,obj,previous,start,engine):
    dt=context.scene.render.fps/context.scene.render.fps_base/30
    strip=previous[1];end=max(strip.frame_end,start)
    history=continuity.sample(context,obj,previous,[max(strip.frame_start,end+i*dt) for i in (-3,-2,-1,0)],
                              include_user=bool(obj.animation_data.action and obj.animation_data.action.get('toyxyz_correction_offsets')),
                              read_pose=rig.model_snapshot)
    pose=dict(history[-1],frame=start,kind='FULL',source='previous_motion_end')
    if engine=='motionbricks':pose['history']=history
    return pose


def targets(context,obj,blocks,engine='kimodo',object_goals=(),following=False):
    """Evaluate only keyed poses used by this job, restoring the user's current pose."""
    values=[f for f in frames(obj,force=True,model_only=True) if any(b['start']<=f<b['end'] for b in blocks)]
    if values:pose_constraints.sync(obj,force=True)
    if any(abs(f-round(f))>1e-4 for f in values):raise ValueError('Move SOMA pose keys to whole frames before generating.')
    start=blocks[0]['start']
    fps=context.scene.render.fps/context.scene.render.fps_base
    end=blocks[-1]['end']
    def model_index(frame):return model_frame_index(frame,start,end,fps)
    goals={}
    if object_goals:
        if engine=='motionbricks':raise ValueError('MotionBricks requires Full Body pose keys. Use Kimodo or ARDY for object constraints.')
        occupied={model_index(f):f for f in values if pose_constraints.kind(obj,f)=='FULL'}
        for goal in object_goals:
            frame=goal['frame'];index=model_index(frame)
            if index in occupied:
                raise ValueError(f'Object constraint at frame {frame} overlaps the Full Body key at frame {occupied[index]:g}. Change the key type or move the marker.')
            goals.setdefault(frame,{})[goal['kind']]=goal
    start_is_target=any(model_index(f)==0 for f in (*values,*goals))
    previous=continuity.predecessor(obj,start,{b.get('uid') for b in blocks if b.get('uid')}) if not start_is_target else None
    if engine=='motionbricks':
        partial=[f for f in values if pose_constraints.kind(obj,f)!='FULL']
        if partial:raise ValueError(f'MotionBricks requires Full Body constraints. Change keyframe {partial[0]:g} to Full Body or use Kimodo/ARDY.')
        validate_motionbricks_times(values,start,end,fps,inherited=previous is not None,following=following)
    if not values and not goals and previous is None:return []
    animation=obj.animation_data
    if animation and animation.use_tweak_mode:raise ValueError('Exit NLA Tweak Mode before generating from the input Action.')
    scene=context.scene;frame=scene.frame_current;subframe=scene.frame_subframe
    def save(item):return {name:getattr(item,name).copy() if hasattr(getattr(item,name),'copy') else tuple(getattr(item,name)) for name in TRANSFORMS}
    saved=[(obj,save(obj)),*[(bone,save(bone)) for bone in obj.pose.bones]]
    saved_modes={bone.name:bone.rotation_mode for bone in obj.pose.bones}
    active_action=animation.action if animation else None;active_slot=animation.action_slot if animation else None
    source,slot=rig.pose_action(obj)
    result=[]
    try:
        with nla_motion.authoring(context,obj):
            if active_action!=source:
                if rig.POSE_BASE in obj:rig.restore_pose_state(obj,json.loads(obj[rig.POSE_BASE]))
                rig.assign_action(obj,source,slot)
            for value in sorted(set(values)|goals.keys()):
                scene.frame_set(round(value));context.view_layer.update()
                pose=dict(rig.model_snapshot(context,obj),frame=round(value))
                if engine=='motionbricks':
                    # Native Action samples communicate velocity/acceleration at interior targets.
                    dt=scene.render.fps/scene.render.fps_base/30
                    def sample(offset):
                        at=value+offset*dt;whole=math.floor(at)
                        scene.frame_set(whole,subframe=at-whole);context.view_layer.update()
                        return rig.model_snapshot(context,obj)
                    if value==values[0]:pose['history']=[sample(i) for i in (-3,-2,-1,0)]
                    if value!=values[-1]:pose['target_poses']=[sample(i) for i in (0,1,2,3)]
                frame_goals=goals.get(value,{})
                kinds=pose_constraints.kinds(obj,value) if value in values else ()
                for kind in kinds:
                    if kind in frame_goals:continue
                    target=dict(pose,kind=kind)
                    if kind=='ROOT' and pose_constraints.uses_heading(obj,value):target['root_heading']=True
                    if kind=='ROOT' and pose_constraints.uses_height(obj,value):target['root_height']=True
                    result.append(target)
                for kind,goal in frame_goals.items():
                    target=dict(pose,kind=kind,source='object',object_goal=goal)
                    if 'heading' in goal:target['root_heading']=True
                    if goal.get('height'):target['root_height']=True
                    result.append(target)
            if previous is not None:
                result.append(inherited_pose(context,obj,previous,start,engine))
    finally:
        # authoring() restores evaluation flags and re-evaluates the current frame.
        # Restore live edits after that context exits, or animation replaces them.
        if animation:rig.assign_action(obj,active_action,active_slot)
        scene.frame_set(frame,subframe=subframe)
        for bone in obj.pose.bones:bone.rotation_mode=saved_modes[bone.name]
        for item,channels in saved:
            for channel,value in channels.items():setattr(item,channel,value)
        obj.update_tag(refresh={'OBJECT','DATA'})
        context.view_layer.update()
    return sorted(result,key=lambda pose:pose['frame'])


def begin_move(obj,frame):
    records=[]
    for fc in curves(obj,include_modes=True):
        for point in fc.keyframe_points:
            if abs(point.co.x-frame)<1e-4:
                records.append((fc,point,point.co.copy(),point.handle_left.copy(),point.handle_right.copy()))
    return records


def move(records,delta):
    # Delay FCurve.update until the drag ends: sorting would invalidate point references.
    for _,point,co,left,right in records:
        point.co=(co.x+delta,co.y)
        point.handle_left=(left.x+delta,left.y);point.handle_right=(right.x+delta,right.y)
    clear()


def finish_move(records):
    for fc in {fc.as_pointer():fc for fc,*_ in records}.values():fc.update()
    clear()
