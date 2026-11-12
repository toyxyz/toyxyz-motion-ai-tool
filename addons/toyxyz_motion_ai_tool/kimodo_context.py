"""Sample adjacent generated motion at the model's 30 Hz rate."""
import hashlib
import json
import math
from . import continuity,nla_motion,rig


def signature(data):
    def quantize(value):
        if isinstance(value,float):
            rounded=round(value,6)
            return rounded if rounded else 0.0
        if isinstance(value,(list,tuple)):return [quantize(item) for item in value]
        if isinstance(value,dict):return {key:quantize(item) for key,item in value.items()}
        return value
    payload=json.dumps(quantize(data),sort_keys=True,separators=(',',':'))
    return hashlib.sha256(payload.encode()).hexdigest()


def previous_motion(context,obj,blocks,history_frames=None):
    first=blocks[0];start=first['start']
    previous=continuity.predecessor(obj,start,{b.get('uid') for b in blocks if b.get('uid')})
    if previous is None or abs(previous[1].frame_end-start)>.0001:return None
    strip=previous[1];fps=context.scene.render.fps/context.scene.render.fps_base
    available=math.floor((strip.frame_end-strip.frame_start)*30/fps+1e-6)
    requested=history_frames if history_frames is not None else first.get('transition_frames',5)
    count=min(requested,available)
    if count<1:return None
    if history_frames is None and count<requested:
        first['requested_transition_frames']=requested
        first['transition_frames']=count
    # Encode at least five samples for velocity/smoothing features, then the
    # worker uses only the requested tail. One-frame overlaps remain valid.
    samples=max(5,count);times=[start-(samples-i)*fps/30 for i in range(samples)]
    poses=sample(context,obj,previous,times)
    return dict(uid=strip.action.get('toyxyz_block_uid',''),engine=strip.action.get(nla_motion.ENGINE,''),
                frame_count=count,sample_frames=times,poses=poses)


def following_clip(obj,settings,blocks):
    end=blocks[-1]['end']
    excluded={b.get('uid') for b in blocks}
    neighbors={b.uid:b for b in settings.blocks if b.enabled and b.start==end and b.uid not in excluded}
    track=continuity.playback(obj)
    if not track or track.mute:return None
    for strip in track.strips:
        if strip.mute or not nla_motion.owned(obj,strip) or strip.action.get(nla_motion.REQUEST):continue
        block=neighbors.get(strip.action.get('toyxyz_block_uid'))
        if block and abs(strip.frame_start-end)<.0001:
            return track,strip,block
    return None


def following_reference(item,blocks,engine):
    _,strip,block=item
    overlap=4
    if engine=='kimodo':
        overlap=block.transition_frames if block.engine=='kimodo' else blocks[-1].get('transition_frames',5)
    return dict(uid=block.uid,action_uid=strip.action.session_uid,overlap=overlap,clip_end=strip.frame_end)


def following_motion(context,obj,blocks,engine,item):
    end=blocks[-1]['end'];fps=context.scene.render.fps/context.scene.render.fps_base
    reference=following_reference(item,blocks,engine)
    available=math.floor((reference['clip_end']-end)*30/fps+1e-6)
    count=min(reference['overlap'],max(1,available))
    times=[end+i*fps/30 for i in range(count)]
    return dict(reference=reference,sample_frames=times,poses=sample(context,obj,item[:2],times))


def sample(context,obj,item,times):
    include_user=bool(obj.animation_data.action and obj.animation_data.action.get('toyxyz_correction_offsets'))
    saved=rig.pose_state(obj);channels={name:tuple(getattr(obj,name)) for name in rig.TRANSFORM_CHANNELS}
    try:return continuity.sample(context,obj,item,times,include_user=include_user,read_pose=rig.model_snapshot)
    finally:
        rig.restore_pose_state(obj,saved)
        for name,value in channels.items():setattr(obj,name,value)
        context.view_layer.update()
