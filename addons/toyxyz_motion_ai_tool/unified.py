"""User Action corrections above native generated NLA, without frame switching."""
from contextlib import contextmanager
import math
import bpy

ENABLED='toyxyz_unified_edit'
OFFSETS='toyxyz_correction_offsets'
BACKUP='toyxyz_absolute_keys_backup'


@contextmanager
def suspend():
    # Sampling callers retain this interface; playback has no Python callback.
    yield


def curves(obj):
    from . import keyframes
    result=keyframes.curves(obj)
    if any(fc.modifiers or fc.sampled_points for fc in result):
        raise ValueError('Convert pose F-Curve modifiers and sampled curves to ordinary keys before correction-layer conversion.')
    return result


def capture(context,obj,ranges=None):
    """Transient composed poses at existing native keys, for migration/regeneration."""
    from . import continuity
    ad=obj.animation_data
    if not ad or not ad.action:return {}
    values={}
    for fc in curves(obj):
        for point in fc.keyframe_points:
            at=float(point.co.x)
            if ranges is None or any(start<=at<=end for start,end in ranges):
                values.setdefault(at,{}).setdefault(fc.data_path,set()).add(fc.array_index)
    if not values:return {}
    scene=context.scene;frame=(scene.frame_current,scene.frame_subframe)
    flags=(ad.use_nla,ad.action_influence,ad.action_blend_type)
    track=continuity.playback(obj);solo=track.is_solo if track else False
    result={}
    try:
        if track:track.is_solo=False
        ad.use_nla=bool(track);ad.action_influence=1
        ad.action_blend_type='COMBINE' if ad.action.get(OFFSETS) or (obj.get(ENABLED) and flags[2]=='COMBINE') else 'REPLACE'
        for at,paths in sorted(values.items()):
            whole=math.floor(at);scene.frame_set(whole,subframe=at-whole);context.view_layer.update()
            result[at]={path:(tuple(obj.path_resolve(path)),indices) for path,indices in paths.items()}
    finally:
        ad.use_nla,ad.action_influence,ad.action_blend_type=flags
        if track:track.is_solo=solo
        scene.frame_set(frame[0],subframe=frame[1]);context.view_layer.update()
    return result


def channelbag(action,slot):
    layer=action.layers[0] if action.layers else action.layers.new('User Corrections')
    strip=next((s for s in layer.strips if s.type=='KEYFRAME'),None)
    if not strip:strip=layer.strips.new(type='KEYFRAME')
    return strip.channelbag(slot,ensure=True)


def copy_keyframe_points(source,target):
    points=target.keyframe_points
    points.clear()
    if source.keyframe_points:points.add(len(source.keyframe_points))
    for old,new in zip(source.keyframe_points,points):
        new.co=old.co;new.interpolation=old.interpolation;new.type=old.type
        new.easing=old.easing;new.amplitude=old.amplitude;new.back=old.back;new.period=old.period
        new.handle_left_type=old.handle_left_type;new.handle_right_type=old.handle_right_type
        new.handle_left=old.handle_left;new.handle_right=old.handle_right
        new.select_control_point=old.select_control_point
        new.select_left_handle=old.select_left_handle;new.select_right_handle=old.select_right_handle
    target.update()


def restore_keyframes(action,slot,backup,paths):
    """Restore edited channels on the original Action, including their key handles."""
    from . import rig
    if action.is_action_layered and slot:
        old_slot=rig.action_slot(backup,slot.handle)
        for li,layer in enumerate(action.layers):
            for si,strip in enumerate(layer.strips):
                if strip.type!='KEYFRAME':continue
                bag=strip.channelbag(slot)
                if not bag:continue
                old_layer=backup.layers[li] if li<len(backup.layers) else None
                old_strip=old_layer.strips[si] if old_layer and si<len(old_layer.strips) else None
                original=old_strip.channelbag(old_slot) if old_strip and old_slot else None
                for curve in list(bag.fcurves):
                    if curve.data_path not in paths:continue
                    old=original.fcurves.find(curve.data_path,index=curve.array_index) if original else None
                    if old is None:bag.fcurves.remove(curve)
                    elif not old.sampled_points:copy_keyframe_points(old,curve)
                names={group.name for group in original.groups} if original else set()
                for group in list(bag.groups):
                    if group.name not in names and not group.channels:bag.groups.remove(group)
    elif not action.is_action_layered:
        for curve in list(action.fcurves):
            if curve.data_path not in paths:continue
            old=backup.fcurves.find(curve.data_path,index=curve.array_index)
            if old is None:action.fcurves.remove(curve)
            elif not old.sampled_points:copy_keyframe_points(old,curve)


def rebase(context,obj,poses):
    """Solve native Combine keys on a temporary Action, then commit user keys only."""
    from . import rig,keyframes
    ad=obj.animation_data;source,slot=rig.pose_action(obj)
    if not source or not poses:return
    work=source.copy();work.use_fake_user=False
    work_slot=rig.action_slot(work,slot.handle)
    frame=(context.scene.frame_current,context.scene.frame_subframe)
    try:
        rig.assign_action(obj,work,work_slot)
        ad.use_nla=True;ad.action_blend_type='COMBINE';ad.action_influence=1
        for at,paths in sorted(poses.items()):
            whole=math.floor(at);context.scene.frame_set(whole,subframe=at-whole);context.view_layer.update()
            for path,(value,indices) in paths.items():
                parent,prop=path.rsplit('.',1);target=obj.path_resolve(parent)
                setattr(target,prop,value)
                for index in (-1,) if prop=='rotation_quaternion' else sorted(indices):
                    if not obj.keyframe_insert(data_path=path,index=index,frame=at):
                        raise ValueError('Cannot insert correction keys. Exit NLA Tweak/Solo modes and unlock pose curves.')
        completed=keyframes.curves(obj)
        if not source.get(OFFSETS) and not source.get(BACKUP):
            backup=source.copy();backup.name=source.name+' · Absolute Keys Backup';backup.use_fake_user=True
            source[BACKUP]=backup.name
        bag=channelbag(source,slot)
        for fc in completed:
            target=bag.fcurves.find(fc.data_path,index=fc.array_index)
            if target is None:target=bag.fcurves.new(data_path=fc.data_path,index=fc.array_index)
            copy_keyframe_points(fc,target)
        source[OFFSETS]=True;keyframes.clear()
    finally:
        rig.assign_action(obj,source,slot)
        if work.users==0:bpy.data.actions.remove(work)
        context.scene.frame_set(frame[0],subframe=frame[1]);context.view_layer.update()


def clean_base(obj):
    """Keep legacy object/custom channels on the user Action, without doubling them."""
    from . import continuity,rig,control_rig
    track=continuity.playback(obj)
    if not track:return
    paths={obj.pose.bones[name].path_from_id(channel) for name in control_rig.names(obj) for channel in rig.TRANSFORM_CHANNELS}
    for strip in track.strips:
        if not strip.action or not strip.action_slot:continue
        action=strip.action;slot=strip.action_slot
        bags=[s.channelbag(slot) for layer in action.layers for s in layer.strips if s.type=='KEYFRAME']
        if not any(fc.data_path not in paths for bag in bags if bag for fc in bag.fcurves):continue
        copy=action.copy();copy.use_fake_user=False;copy_slot=rig.action_slot(copy,slot.handle)
        for layer in copy.layers:
            for s in layer.strips:
                if s.type!='KEYFRAME':continue
                bag=s.channelbag(copy_slot)
                if bag:
                    for fc in list(bag.fcurves):
                        if fc.data_path not in paths:bag.fcurves.remove(fc)
        action.use_fake_user=True
        strip.action=copy;strip.action_slot=copy_slot


def correction_curves(obj):
    from . import correction_bounds
    return {(fc.data_path,fc.array_index):fc for fc in curves(obj)},correction_bounds.curves(obj)


def correction_value(path,channel,frame,fallback,corrections):
    from mathutils import Quaternion
    curves,bounds=corrections
    defaults=(1,0,0,0) if channel=='rotation_quaternion' else (0,)*len(fallback)
    values=[curves[path,i].evaluate(frame) if (path,i) in curves else value for i,value in enumerate(fallback)]
    if channel=='rotation_quaternion':
        q=Quaternion(values)
        if q.magnitude<1e-8:q=Quaternion()
        else:q.normalize()
        if not bounds:return q
        guard=[bounds[path,i].evaluate(frame) if (path,i) in bounds else defaults[i] for i in range(len(fallback))]
        return Quaternion(guard).normalized()@q
    if not bounds:return values
    guard=[bounds[path,i].evaluate(frame) if (path,i) in bounds else defaults[i] for i in range(len(fallback))]
    return [value+bound-default for value,bound,default in zip(values,guard,defaults)]


def full_body_overrides(obj,block,poses):
    """Only FB targets require exact authored local channels in the new base.

    An end-effector target permits a different shoulder/elbow configuration.
    Forcing its old FK keys at just that frame creates a one-frame pop. Keep
    the source correction Action intact and remove that correction from the
    generated base normally, without introducing this extra keyed-frame snap.
    """
    from . import pose_constraints
    kinds={float(frame):kind for frame,kind in block.get('constraint_types',())}
    return {frame:channels for frame,channels in poses.items()
            if kinds.get(float(frame),pose_constraints.kind(obj,frame))=='FULL'}


def components(obj,name,channel,frame,desired,corrections,poses):
    """Bake the lower layer excluding the already-present upper correction.

    The model sees composed pose targets. Removing that same correction from
    the new base prevents applying it twice, including an inherited start with
    no user key. Authored Full Body components remain exact at their key frames.
    """
    from mathutils import Quaternion
    path=obj.pose.bones[name].path_from_id(channel)
    values=list(desired)
    record=poses.get(float(frame),{}).get(path)
    if record:
        target,indices=record
        for i in indices:values[i]=target[i]
    # Native Combine treats axis-angle components as additive scalar channels.
    defaults=(1,0,0,0) if channel=='rotation_quaternion' else (0,)*len(values)
    delta=correction_value(path,channel,frame,defaults,corrections)
    if channel=='rotation_quaternion':
        return Quaternion(values)@delta.inverted()
    return [value-offset+default for value,offset,default in zip(values,delta,defaults)]


def enable(context,obj,poses=None):
    from . import continuity,rig
    # Wait for withdrawn control data to be discarded on a safe scene update.
    if obj.get('toyxyz_control_rig_v1'):return
    ad=obj.animation_data_create()
    if ad.use_tweak_mode:raise ValueError('Exit NLA Tweak Mode before editing motion.')
    source=ad.action
    if source is None:
        source=bpy.data.actions.new('User Corrections')
        slot=source.slots.new(id_type='OBJECT',name=obj.name)
        rig.assign_action(obj,source,slot);source[OFFSETS]=True
    migrating=bool(source and not source.get(OFFSETS))
    if poses is None and migrating:poses=capture(context,obj)
    track=continuity.playback(obj)
    if track:track.is_solo=False
    ad.use_nla=True;ad.action_blend_type='COMBINE';ad.action_influence=1
    clean_base(obj)
    if poses:rebase(context,obj,poses)
    if source:source[OFFSETS]=True
    obj[ENABLED]=True;obj['toyxyz_nla_preview']=True;obj['toyxyz_author_influence']=1.0
    from . import correction_bounds
    correction_bounds.sync(context.scene,obj)


def register():pass


def unregister():pass
