"""Persist ARDY's native join data and keep the existing swing animation."""
import hashlib
import json
import math
from bisect import bisect_left

import bpy
from mathutils import Euler, Quaternion

from . import continuity, control_rig, keyframes, nla_motion, timeline

RAW_BLOCK = 'toyxyz_ardy_raw_block'
JOIN = 'toyxyz_ardy_join'
JOIN_INFO = 'toyxyz_ardy_join_info'
MODEL_RATE = 30
SWING_BLEND = 3


def identifier(action):
    job = action.get('toyxyz_job_id')
    block = action.get('toyxyz_block_uid')
    return f'{job}:{block}' if job and block else None


def intact(strip):
    return (abs(strip.scale-1)<1e-4
            and abs(strip.action_frame_start-strip.action.frame_start)<1e-4
            and abs(strip.action_frame_end-strip.action.frame_end)<1e-4
            and abs((strip.frame_end-strip.frame_start)-
                    (strip.action.frame_end-strip.action.frame_start))<1e-4)


def payload(context, obj, blocks, poses, history):
    from . import seam_blend

    if not history or history.get('engine')!='ardy' or blocks[0].get('root_path'):
        return None
    first=blocks[0]
    cut=first['start']
    fps=timeline.fps(context.scene)
    count=(first['end']-cut)*MODEL_RATE/fps
    if round(count)<2 or abs(count-round(count))>1e-4:
        return None
    if any(cut<=p['frame']<first['end'] and p.get('source')!='previous_motion_end' for p in poses):
        return None
    item=continuity.predecessor(obj,cut,{b['uid'] for b in blocks})
    if not item:
        return None
    strip=item[1]
    if (abs(strip.frame_end-cut)>1e-4
        or not intact(strip) or not seam_blend.simple(strip) or RAW_BLOCK not in strip.action):
        return None
    if any(strip.frame_start<=frame<cut for frame in keyframes.frames(obj,force=True,model_only=True,include_modes=True)):
        return None
    saved=json.loads(strip.action[RAW_BLOCK])
    if abs(saved['scene_fps']-fps)>1e-4:
        return None
    if abs((strip.frame_end-strip.frame_start)*MODEL_RATE/fps-saved['motion']['count'])>1e-4:
        return None
    ident=identifier(strip.action)
    return dict(saved['motion'],id=ident) if ident else None


def remember(action, data, block):
    if data['engine']!='ardy':
        return
    motion=data.get('ardy_blocks',{}).get(block['uid'])
    if not motion:
        return
    expected=next((item for item in data['blocks'] if item['uid']==block['uid']),None)
    if not expected or (block['start'],block['end'])!=(expected['start'],expected['end']):
        return
    action[RAW_BLOCK]=json.dumps(dict(scene_fps=data['scene_fps'],motion=motion),separators=(',',':'))
    join=data.get('ardy_join')
    if join and block['start']==data['start']:
        joined=dict(join,scene_fps=data['scene_fps'])
        encoded=json.dumps(joined,separators=(',',':'))
        action[JOIN]=encoded
        action[JOIN_INFO]=json.dumps(dict(previous=join['previous'],scene_fps=data['scene_fps'],
                                        left_count=join['left_count'],count=len(join['root_positions'])))
        action[JOIN+'_signature']=hashlib.sha256(encoded.encode()).hexdigest()


def window(left, right, fps, protected):
    if (left.action.get(nla_motion.ENGINE)!='ardy' or right.action.get(nla_motion.ENGINE)!='ardy'
        or JOIN not in right.action or not intact(left) or not intact(right)):
        return None
    cut=round(right.frame_start)
    step=fps/MODEL_RATE
    info=right.action.get(JOIN_INFO)
    if not info:
        # Older Actions still reproduce their original short transition.
        motion=json.loads(right.action[JOIN])
        if motion.get('left_count') or motion['previous']!=identifier(left.action) or abs(motion['scene_fps']-fps)>1e-4:
            return None
        origin=cut-10*step
        start,end=math.ceil(origin-1e-6),math.floor(cut+9*step+1e-6)
        if start<left.frame_start or end>right.frame_end or any(start<=frame<=end for frame in protected):
            return None
        return start,end,origin
    motion=json.loads(info)
    if motion['previous']!=identifier(left.action) or abs(motion['scene_fps']-fps)>1e-4:
        return None
    origin=cut-motion['left_count']*step
    finish=origin+motion['count']*step
    if abs(origin-left.frame_start)>1e-4 or abs(finish-right.frame_end)>1e-4:
        return None
    if any(origin<=frame<=finish for frame in protected):
        return None
    return round(origin),round(finish),origin


def overlay(obj, left, right, start, end, origin, baseline, base_start, base_end):
    """Mix native correction with existing FK/IK control channels by limb."""
    from . import seam_blend

    old,new=seam_blend.channels(left),seam_blend.channels(right)
    if not baseline or old.keys()!=new.keys():
        return {}
    motion=json.loads(right.action[JOIN])
    full=bool(motion.get('left_count'))
    # Baking uses the same coordinate conversion and correction layer as the base clips.
    action,slot=nla_motion.bake_action(obj,dict(motion,start=origin,end=end,fps=MODEL_RATE,engine='ardy'),
                                       dict(start=start,end=end,name='ARDY boundary',uid='ardy-boundary'))
    try:
        curves={}
        for curve in control_rig.action_curves(action,slot):
            curves.setdefault(curve.data_path,{})[curve.array_index]=curve
        if old.keys()!=curves.keys():
            return {}
        limb_paths={}
        controlled=control_rig.enabled(obj)
        for side, index in (('Left',0),('Right',1)):
            names=[side+suffix for suffix in ('Leg','Shin','Foot','ToeBase')]
            if controlled:
                limb=control_rig.LIMBS[side+'Leg']
                names=[*map(control_rig.fk,names),limb['target'],limb['pole']]
            for name in names:
                limb_paths[obj.pose.bones[name].path_from_id()]=index
        step=motion['scene_fps']/MODEL_RATE
        contacts=motion['contacts']
        planted=[[i for i,flags in enumerate(contacts) if max(flags[2*j:2*j+2])>.5] for j in (0,1)]
        weights=[]
        for frame in range(start,end+1):
            sample=(frame-origin)/step
            distances=[]
            for indices in planted:
                index=bisect_left(indices,sample)
                neighbors=indices[max(0,index-1):index+1]
                distances.append(min((abs(i-sample) for i in neighbors),default=SWING_BLEND))
            t=[min(1.,value/SWING_BLEND) for value in distances]
            weights.append([1-value*value*(3-2*value) for value in t])
        result={}
        for path, components in curves.items():
            prefix,prop=path.rsplit('.',1)
            side=limb_paths.get(prefix)
            mode=obj.path_resolve(prefix).rotation_mode
            samples=[]
            for frame in range(start,end+1):
                if base_start<=frame<=base_end:
                    normal=baseline[path][frame-base_start]
                elif frame<base_start:
                    normal=seam_blend.read(left,old[path],frame)
                else:
                    normal=seam_blend.read(right,new[path],frame)
                fade=max(1.,SWING_BLEND*step) if full else 1.
                edge=min(1.,(frame-start)/fade,(end-frame)/fade)
                weight=edge*edge*(3-2*edge)*(1. if side is None else weights[frame-start][side])
                value=tuple(components[i].evaluate(frame) for i in range(len(components)))
                if prop=='location':
                    mixed=tuple((1-weight)*a+weight*b for a,b in zip(normal,value))
                else:
                    q=seam_blend.rotation(prop,normal,mode).slerp(seam_blend.rotation(prop,value,mode),weight)
                    if prop=='rotation_quaternion':
                        if samples and q.dot(Quaternion(samples[-1]))<0:q.negate()
                        mixed=tuple(q)
                    elif prop=='rotation_euler':
                        previous=Euler(samples[-1],mode) if samples else None
                        mixed=tuple(q.to_euler(mode,previous))
                    else:
                        axis,angle=q.to_axis_angle()
                        mixed=(angle,*axis)
                samples.append(mixed)
            result[path]=samples
        return result
    finally:
        bpy.data.actions.remove(action)
