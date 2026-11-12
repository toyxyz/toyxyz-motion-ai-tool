"""Keep a new correction from extending back into preceding motion blocks."""
from contextlib import contextmanager
import json
import math

import bpy
from mathutils import Quaternion

TAG='toyxyz_correction_bounds'
LABEL='Motion AI · Correction Boundaries'
_replacement={}


@contextmanager
def replace_on_success(obj):
    """Keep the original boundary track available until the new result commits."""
    key=obj.as_pointer()
    original=track(obj)
    state={'original':original,'retired':False}
    _replacement[key]=state
    try:
        yield
        if state['retired']:remove(obj.animation_data,original)
    finally:
        del _replacement[key]


def retire(obj,layer):
    state=_replacement.get(obj.as_pointer())
    if state and layer==state['original']:
        layer.mute=True
        state['retired']=True
    else:
        remove(obj.animation_data,layer)


def track(obj):
    animation=obj.animation_data
    if not animation:return None
    state=_replacement.get(obj.as_pointer())
    retired=state['original'] if state and state['retired'] else None
    return next((t for t in animation.nla_tracks
                 if t!=retired and any(s.action and TAG in s.action for s in t.strips)),None)


def remove(animation,layer):
    actions={s.action for s in layer.strips if s.action and TAG in s.action}
    animation.nla_tracks.remove(layer)
    for action in actions:
        if not action.users:bpy.data.actions.remove(action)


def values(curves,blocks,first_frame):
    groups={}
    for curve in curves:
        if not curve.keyframe_points or curve.extrapolation!='CONSTANT' or curve.modifiers:continue
        path=curve.data_path
        key=(path,-1 if path.endswith('.rotation_quaternion') else curve.array_index)
        groups.setdefault(key,[]).append(curve)
    result=[]
    for (path,index),channels in groups.items():
        at=min(fc.keyframe_points[0].co.x for fc in channels)
        begin=next((b.start for b in blocks if b.start<=at<b.end),at)
        if begin<=first_frame:continue
        if index==-1:
            q=Quaternion()
            for fc in channels:q[fc.array_index]=fc.evaluate(at)
            if q.magnitude<1e-8:continue
            if q.w<0:q.negate()
            neutral=(1.,0.,0.,0.)
            inverse=q.normalized().inverted()
            samples=zip(range(4),inverse,neutral)
        else:
            value=channels[0].evaluate(at)
            if path.endswith('.scale'):
                if abs(value)<1e-8:continue
                samples=((index,1./value,1.),)
            else:samples=((index,-value,0.),)
        for channel,inverse,neutral in samples:
            if abs(inverse-neutral)>1e-7:
                result.append((path,channel,begin,at,inverse,neutral))
    return result


def sync(scene,obj,first_frame=None):
    from . import continuity,control_layers,keyframes,nla_motion,rig_store,unified
    animation=obj.animation_data
    if not animation or animation.use_tweak_mode:return
    old=track(obj)
    playback=continuity.playback(obj)
    settings=rig_store.for_rig(scene,obj)
    authored=animation.action
    bounds=[]
    if playback and playback.strips:
        current=playback.strips[0].frame_start
        first_frame=current if first_frame is None else min(first_frame,current)
    if first_frame is not None and authored and authored.get(unified.OFFSETS) and settings:
        bounds=values(keyframes.curves(obj),settings.blocks,first_frame)
    if not bounds:
        if old:retire(obj,old)
        return
    signature=json.dumps(bounds,separators=(',',':'))
    if old and old.strips[0].action.get(TAG)==signature:
        order=list(animation.nla_tracks)
        layers=control_layers.rows(obj)
        if (playback is None or order.index(old)>order.index(playback)) and (not layers or order.index(old)<order.index(layers[0][0])):return

    action=bpy.data.actions.new(LABEL)
    action[TAG]=signature
    slot=action.slots.new(id_type='OBJECT',name=obj.name)
    bag=unified.channelbag(action,slot)
    start=math.floor(min(b[2] for b in bounds))-1
    end=math.ceil(max(b[3] for b in bounds))+1
    action.use_frame_range=True;action.frame_start=start;action.frame_end=end
    for path,index,begin,at,inverse,neutral in bounds:
        curve=bag.fcurves.new(data_path=path,index=index)
        first=curve.keyframe_points.insert(begin if begin<at else at-1,inverse)
        first.interpolation='LINEAR' if begin<at else 'CONSTANT'
        curve.keyframe_points.insert(at,neutral)
        curve.update()
    layer=control_layers.new_lower_track(obj)
    try:
        layer.name=LABEL
        strip=nla_motion.create_strip(obj,layer,action,slot,start,end,LABEL)
        strip.blend_type='COMBINE';strip.select=False
        layer.lock=True
    except Exception:
        animation.nla_tracks.remove(layer)
        if not action.users:bpy.data.actions.remove(action)
        raise
    if old:retire(obj,old)
    if playback:animation.nla_tracks.active=playback
    obj.update_tag(refresh={'OBJECT'})


def curves(obj):
    layer=track(obj)
    if not layer or layer.mute:return {}
    strip=layer.strips[0]
    if strip.mute:return {}
    bag=strip.action.layers[0].strips[0].channelbag(strip.action_slot)
    return {(curve.data_path,curve.array_index):curve for curve in bag.fcurves}
