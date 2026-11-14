"""Bake short joins between independently generated clips into native NLA."""
import json
import math

import bpy
from mathutils import Euler, Quaternion, Vector

from . import ardy_transition, control_rig, correction_bounds, keyframes, nla_motion, rig_store, unified


LABEL = 'Motion AI · Block Transitions'
TAG = 'toyxyz_block_transition'
TRACK_STATE = 'toyxyz_transition_state'
# Refresh saved transition Actions for the current join rules.
REVISION = 5
TRANSFORMS = {'location': 3, 'rotation_quaternion': 4,
              'rotation_euler': 3, 'rotation_axis_angle': 4}


def simple(strip):
    return (strip.action_slot and not strip.use_reverse and strip.repeat == 1
            and not strip.use_animated_time and not strip.use_animated_influence
            and strip.blend_type == 'REPLACE'
            and not strip.blend_in and not strip.blend_out and not strip.modifiers)


def candidates(scene, obj, playback):
    if not playback or playback.mute:
        return []
    clips = [s for s in playback.strips if not s.mute and nla_motion.owned(obj,s)
             and not s.action.get(nla_motion.REQUEST)]
    fps = scene.render.fps / scene.render.fps_base
    result = []
    for left,right in zip(clips,clips[1:]):
        frame = right.frame_start
        if (abs(left.frame_end-frame)>1e-4 or abs(frame-round(frame))>1e-4
                or not simple(left) or not simple(right)):
            continue
        # Clips split from one worker result already share the exact same sample.
        job = left.action.get('toyxyz_job_id')
        if not job or not right.action.get('toyxyz_job_id') or job == right.action.get('toyxyz_job_id'):
            continue
        before = math.floor(min(round(fps * .10),(frame-left.frame_start)/3))
        after = math.floor(min(round(fps * .10),(right.frame_end-frame)/3))
        if min(before,after)>=1:
            result.append((left,right,round(frame)-before,round(frame)+after))
    return result


def channels(strip):
    groups = {}
    for curve in control_rig.action_curves(strip.action,strip.action_slot):
        path = curve.data_path
        prop = path.rsplit('.',1)[-1]
        if path.startswith('pose.bones[') and prop in TRANSFORMS:
            if curve.mute or curve.modifiers or curve.sampled_points:
                return {}
            groups.setdefault(path,{})[curve.array_index] = curve
    result = {}
    for path,items in groups.items():
        indices = range(TRANSFORMS[path.rsplit('.',1)[-1]])
        if not all(i in items for i in indices):
            return {}
        result[path] = [items[i] for i in indices]
    return result


def read(strip, curves, frame):
    at = strip.action_frame_start + (frame - strip.frame_start) / strip.scale
    return tuple(curve.evaluate(at) for curve in curves)


def rotation(prop, values, mode):
    if prop == 'rotation_quaternion':
        return Quaternion(values).normalized()
    if prop == 'rotation_euler':
        return Euler(values,mode).to_quaternion()
    if Vector(values[1:]).length_squared < 1e-10:
        return Quaternion()
    return Quaternion(values[1:],values[0])


def rotation_delta(left, right, steps):
    delta = left.rotation_difference(right)
    if delta.w < 0:
        delta.negate()
    axis,angle = delta.to_axis_angle()
    return Quaternion(axis, angle * steps)


def coefficients(before,left,right,after,width):
    span = (right-left).length
    first,last = (left-before)*width,(after-right)*width
    # Limit tangent overshoot when the two clips turn or settle in place.
    limit = 2 * span
    for tangent in (first,last):
        if tangent.length>limit:
            tangent.length=limit
    return left,first,last,right


def cubic(values, t):
    a,b,c,d = values
    return (2*t**3-3*t*t+1)*a+(t**3-2*t*t+t)*b+(t**3-t*t)*c+(-2*t**3+3*t*t)*d


def spherical(values, t):
    a,b,c,d = values
    ab,bc,cd = a.slerp(b,t),b.slerp(c,t),c.slerp(d,t)
    return ab.slerp(bc,t).slerp(bc.slerp(cd,t),t)


def guard_value(path, prop, frame, bounds):
    neutral = (1.,0.,0.,0.) if prop=='rotation_quaternion' else (0.,)*TRANSFORMS[prop]
    return tuple(bounds[path,i].evaluate(frame) if (path,i) in bounds else value
                 for i,value in enumerate(neutral))


def blend_curves(obj,left,right,start,end,bounds):
    old,new = channels(left),channels(right)
    if not old or old.keys()!=new.keys():
        return {}
    width = end - start
    result = {}
    hips = control_rig.fk('Hips') if control_rig.enabled(obj) else 'Hips'
    root_path = obj.pose.bones[hips].path_from_id('location')
    for path,curves in old.items():
        prop = path.rsplit('.',1)[-1]
        samples = [read(strip,source,frame) for strip,source,frame in (
            (left,curves,start-1),(left,curves,start),
            (right,new[path],end),(right,new[path],end+1))]
        # Generated actions compensate for the correction guard at bake time.
        # Interpolate with that guard applied, then remove it at each output
        # frame so the native Combine layer applies it exactly once.
        guarded = any((path,i) in bounds for i in range(TRANSFORMS[prop]))
        guard = [guard_value(path,prop,frame,bounds) for frame in
                 (start-1,start,end,end+1)] if guarded else None
        if guard and prop!='rotation_quaternion':
            samples = [tuple(x+y for x,y in zip(value,delta)) for value,delta in zip(samples,guard)]
        if prop=='location':
            vectors = tuple(map(Vector,samples))
            if path==root_path:
                before,first,last,after = vectors
                # Leave large jumps between independently positioned takes intact.
                maximum = width * max((first-before).length,(after-last).length) + .25 * obj['toyxyz_units']
                if (last-first).length > maximum:
                    return {}
            values = coefficients(*vectors,width)
            samples = [cubic(values,i/width) for i in range(round(width)+1)]
        else:
            mode = obj.path_resolve(path.rsplit('.',1)[0]).rotation_mode
            if prop=='rotation_euler' and len(mode)!=3:
                return {}
            values = [rotation(prop,components,mode) for components in samples]
            if guard and prop=='rotation_quaternion':
                values = [q @ Quaternion(delta).normalized() for q,delta in zip(values,guard)]
            a,b,c,d = values
            guides = (b,b@rotation_delta(a,b,width/3),c@rotation_delta(d,c,width/3),c)
            samples = []
            previous = None
            for index in range(round(width)+1):
                q = spherical(guides,index/width)
                if prop=='rotation_quaternion':
                    if guarded:
                        delta = guard_value(path,prop,start+index,bounds)
                        q = q @ Quaternion(delta).normalized().inverted()
                    if previous and q.dot(previous)<0:
                        q.negate()
                    value = q
                elif prop=='rotation_euler':
                    value = q.to_euler(mode,previous) if previous else q.to_euler(mode)
                else:
                    axis,angle = q.to_axis_angle()
                    value = (angle,*axis)
                samples.append(tuple(value))
                previous = value
        if guarded and prop!='rotation_quaternion':
            samples = [tuple(x-y for x,y in zip(value,guard_value(path,prop,start+i,bounds)))
                       for i,value in enumerate(samples)]
        result[path] = samples
    return result


def remove(animation, layer):
    actions = {strip.action for strip in layer.strips if strip.action and TAG in strip.action}
    animation.nla_tracks.remove(layer)
    for action in actions:
        if not action.users:
            bpy.data.actions.remove(action)


def sync(scene,obj,playback,*,force=False):
    animation = obj.animation_data
    old = next((layer for layer in animation.nla_tracks
                if any(strip.action and TAG in strip.action for strip in layer.strips)),None)
    joins = candidates(scene,obj,playback)
    if not joins:
        if old:
            remove(animation,old)
        if TRACK_STATE in obj:
            del obj[TRACK_STATE]
        return
    order = list(animation.nla_tracks)
    index = order.index(playback)+1
    if index<len(order) and any(strip.name.startswith(nla_motion.START_STRIP) for strip in order[index].strips):
        index += 1
    anchor = order[index-1]
    settings = rig_store.for_rig(scene,obj)
    blocks = {b.uid:b for b in settings.blocks} if settings else {}
    protected = set(keyframes.frames(obj,force=force,model_only=True,include_modes=True))
    if settings:
        protected.update(marker.frame for marker in settings.object_constraints if marker.target)
    guard_layer = correction_bounds.track(obj)
    guard = guard_layer.strips[0] if guard_layer and not guard_layer.mute else None
    guard_signature = guard.action.get(correction_bounds.TAG) if guard and not guard.mute else None
    planned = []
    for left,right,start,end in joins:
        cut=round(right.frame_start)
        if cut in protected:
            continue
        # Leave a nearby authored pose at the edge of the join, where the
        # original clip is reproduced exactly.
        start=max([start]+[math.ceil(f) for f in protected if start<f<cut])
        end=min([end]+[math.floor(f) for f in protected if cut<f<end])
        if cut-start<1 or end-cut<1:
            continue
        owners = [blocks.get(s.action.get('toyxyz_block_uid')) for s in (left,right)]
        if any(block and block.path_curve for block in owners):
            continue
        fps=scene.render.fps/scene.render.fps_base
        native=ardy_transition.window(left,right,fps,protected) if not guard_signature else None
        if native or (cut-start>=2 and end-cut>=2):
            planned.append((left,right,start,end,native))
    eligible = []
    for i,(left,right,start,end,native) in enumerate(planned):
        if native:
            a,b,origin=native
            cut=round(right.frame_start)
            # Both solves use their full input. At playback, give each boundary
            # its side of a shared block and fade to the base at the handoff.
            if i and planned[i-1][1]==left:
                earlier=planned[i-1]
                a=max(a,math.floor((left.frame_start+cut)/2) if earlier[-1] else earlier[3])
            if i+1<len(planned) and planned[i+1][0]==right:
                later=planned[i+1]
                b=min(b,math.floor((cut+right.frame_end)/2) if later[-1] else later[2])
            native=(a,b,origin) if a<cut<b else None
        if not native and min(round(right.frame_start)-start,end-round(right.frame_start))<2:
            continue
        signature = json.dumps([
            REVISION,
            [(s.action.name,s.action.get('toyxyz_job_id'),s.frame_start,s.action_frame_start,s.scale)
             for s in (left,right)],start,end,control_rig.enabled(obj),guard_signature,
            [native[0],native[1],right.action.get(ardy_transition.JOIN+'_signature')] if native else None
        ])
        eligible.append((left,right,start,end,native,signature))
    state = json.dumps([item[-1] for item in eligible])
    if old and order.index(old)==index and obj.get(TRACK_STATE)==state:
        return
    if not old and not force and obj.get(TRACK_STATE)==state:
        return
    cached = {s.action.get(TAG):s.action for s in old.strips} if old else {}
    bounds = correction_bounds.curves(obj)
    layer = None
    actions = []
    try:
        for left,right,start,end,native,signature in eligible:
            action = cached.get(signature)
            if action is None:
                values = blend_curves(obj,left,right,start,end,bounds)
                if not values:
                    continue
                if native:
                    a,b,origin=native
                    corrected=ardy_transition.overlay(obj,left,right,a,b,origin,values,start,end)
                    if corrected:
                        values,start,end=corrected,a,b
                action = bpy.data.actions.new(LABEL)
                actions.append(action)
                action[TAG] = signature
                slot = action.slots.new(id_type='OBJECT',name=obj.name)
                bag = unified.channelbag(action,slot)
                for path,samples in values.items():
                    for channel,component in enumerate(zip(*samples)):
                        coordinates = [v for i,value in enumerate(component) for v in (start+i,value)]
                        nla_motion.add_linear_curve(bag,path,channel,coordinates)
                action.use_frame_range=True
                action.frame_start=start
                action.frame_end=end
            else:
                start,end=round(action.frame_start),round(action.frame_end)
            if layer is None:
                layer = animation.nla_tracks.new(prev=anchor)
                layer.name = LABEL
            strip = nla_motion.create_strip(obj,layer,action,action.slots[0],start,end,LABEL)
            strip.extrapolation='NOTHING'
            strip.select=False
        if layer:
            layer.mute=bool(old and old.mute)
            layer.lock=True
    except BaseException:
        if layer:
            animation.nla_tracks.remove(layer)
        for action in actions:
            if not action.users:
                bpy.data.actions.remove(action)
        raise
    if old:
        remove(animation,old)
    obj[TRACK_STATE]=state
    if layer or old:
        animation.nla_tracks.active=playback
        obj.update_tag(refresh={'OBJECT'})
