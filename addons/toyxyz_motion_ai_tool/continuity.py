from . import rig_store
"""One chronological native NLA playback track; obsolete plain tracks are removed.

HOLD is track-local. Keeping live blocks together prevents future tracks from
pre-holding their first pose over an earlier motion. No frame handlers/drivers.
"""
import math
import json
from . import nla_motion

TRACK='toyxyz_playback_track'
READY='toyxyz_playback_ready'
PROPERTIES=('action_frame_start','action_frame_end','repeat','scale','blend_type',
            'influence','mute','use_auto_blend','blend_in','blend_out','use_reverse','use_sync_length',
            'use_animated_influence','use_animated_time','use_animated_time_cyclic','strip_time')


def playback(obj):
    ad=obj.animation_data if obj else None
    if not ad:return None
    name=obj.get(TRACK)
    named=[t for t in ad.nla_tracks if t.name==name] if name else []
    if named:
        active=ad.nla_tracks.active
        if active in named:return active
        return next((t for t in reversed(named) if not t.mute),named[-1])
    # A renamed current track can still be found among unmuted tool results.
    for track in reversed(list(ad.nla_tracks)):
        if not track.mute and any(nla_motion.owned(obj,s) and not s.action.get(nla_motion.REQUEST) for s in track.strips):
            if obj.get(READY):obj[TRACK]=track.name
            return track
    return None


def descriptor(strip):
    return dict(action=strip.action,slot=strip.action_slot,start=strip.frame_start,end=strip.frame_end,name=strip.name,
                settings={name:getattr(strip,name) for name in PROPERTIES},
                curves=[dict(path=fc.data_path,extrapolation=fc.extrapolation,mute=fc.mute,
                             points=[(tuple(p.co),p.interpolation,p.handle_left_type,p.handle_right_type,tuple(p.handle_left),tuple(p.handle_right)) for p in fc.keyframe_points])
                        for fc in strip.fcurves])


def append(obj,track,value):
    # Start in a free slot, then set scene bounds. This also permits temporary
    # authoring overlaps without silently moving another block.
    safe=max([value['start']]+[s.frame_end+1 for s in track.strips])
    strip=nla_motion.create_strip(obj,track,value['action'],value['slot'],safe,safe+value['end']-value['start'],value['name'])
    for name,v in value['settings'].items():setattr(strip,name,v)
    strip.frame_start_raw=value['start'];strip.frame_end_raw=value['end'];strip.extrapolation='HOLD'
    for curve in value['curves']:
        for point in curve['points']:
            setattr(strip,curve['path'],point[0][1]);strip.keyframe_insert(data_path=curve['path'],frame=point[0][0])
        fc=next((c for c in strip.fcurves if c.data_path==curve['path']),None)
        if fc:
            fc.extrapolation=curve['extrapolation'];fc.mute=curve['mute']
            for old,p in zip(curve['points'],fc.keyframe_points):
                p.interpolation=old[1];p.handle_left_type=old[2];p.handle_right_type=old[3]
                p.handle_left=old[4];p.handle_right=old[5]
    return strip


def activate(scene,obj,track):
    """Complete a new generation track with unaffected current blocks, then activate it."""
    had_current=bool(obj.get(READY) and obj.get(TRACK) and obj.animation_data.nla_tracks.get(obj[TRACK]))
    previous=playback(obj);values={}
    # Older installations used multiple simultaneous tracks. Adopt their newest
    # visible result for each block; subsequent generations use the current snapshot.
    sources=[previous] if previous and previous!=track else []
    if not had_current:
        sources=[t for t in obj.animation_data.nla_tracks if t!=track and not t.mute]
    for source in sources:
        for strip in source.strips:
            if nla_motion.owned(obj,strip) and not strip.action.get(nla_motion.REQUEST):
                values[strip.action.get('toyxyz_block_uid')]=descriptor(strip)
    for strip in track.strips:
        if nla_motion.owned(obj,strip):values[strip.action.get('toyxyz_block_uid')]=descriptor(strip)
    # Restrict managed snapshots to blocks still present in the dedicated timeline.
    known={b.uid for b in rig_store.settings(scene).blocks}
    values={uid:v for uid,v in values.items() if uid in known or not v['action'].get('toyxyz_linked_block')}
    for strip in list(track.strips):track.strips.remove(strip)
    for value in sorted(values.values(),key=lambda v:(v['start'],v['end'])):append(obj,track,value)
    for other in obj.animation_data.nla_tracks:
        if other==track:continue
        owned=[s for s in other.strips if nla_motion.owned(obj,s)]
        if owned and len(owned)==len(other.strips):other.mute=True;other.is_solo=False
        else:
            # A user may have mixed generated and unrelated strips on one track.
            for strip in owned:strip.mute=True
    base='Motion AI Playback · '+track.name
    names={other.name for other in obj.animation_data.nla_tracks if other!=track}
    name=base;index=1
    while name in names:name=base+f'.{index:03d}';index+=1
    track.name=name;track.mute=False
    if any(t.is_solo for t in obj.animation_data.nla_tracks):track.is_solo=True
    obj[TRACK]=track.name;obj[READY]=True;obj.animation_data.nla_tracks.active=track
    authoring_prefix(scene,obj)


def authoring_prefix(scene,obj):
    """Empty leading authoring blocks must not pre-hold a future generated clip."""
    track=playback(obj)
    if not track or not track.strips:return
    clips=[strip for strip in track.strips if nla_motion.owned(obj,strip) and not strip.action.get(nla_motion.REQUEST)]
    if not clips:return
    first=min(clips,key=lambda strip:strip.frame_start)
    blocks=rig_store.settings(scene).blocks
    empty_prefix=any(block.enabled and block.start<first.frame_start-.001 and not block.has_result for block in blocks)
    expected='HOLD_FORWARD' if empty_prefix else 'HOLD'
    if first.extrapolation!=expected:first.extrapolation=expected


def initialize(scene):
    obj=rig_store.settings(scene).rig
    if not obj or not obj.animation_data or obj.animation_data.use_tweak_mode:return
    generated=[(track,strip) for track,strip in nla_motion.strips(obj) if not strip.action.get(nla_motion.REQUEST)]
    for _,strip in generated:strip.extrapolation='HOLD'
    if not generated:return
    if obj.get(READY) and obj.get(TRACK) and obj.animation_data.nla_tracks.get(obj[TRACK]):
        cleanup(obj);return
    from . import control_layers
    track=control_layers.new_lower_track(obj);track.name='Imported Motion'
    activate(scene,obj,track)
    cleanup(obj)


def cleanup(obj):
    """Remove inactive tool playback rows, without purging shared Action data.

    Run only after a successful apply (or inside the load transaction), so
    rollback still has its old tracks. Explicitly customized rows stay intact.
    """
    ad=obj.animation_data if obj else None
    if not ad or ad.use_tweak_mode:return 0
    current=playback(obj)
    if current is None:return 0
    count=0
    for track in list(ad.nla_tracks):
        if track==current or not track.mute or track.lock:continue
        if not track.name.startswith(('Motion AI Playback','Kimodo · ','Motionbricks · ')):continue
        clips=list(track.strips)
        if not clips or not all(nla_motion.owned(obj,s) and not s.action.get(nla_motion.REQUEST) for s in clips):continue
        if any(s.modifiers or any(fc.modifiers for fc in s.fcurves) for s in clips):continue
        # Actions can also be used by the new track, user strips or backups.
        # Let Blender manage unused data; never globally purge/delete Actions.
        ad.nla_tracks.remove(track);count+=1
    return count


def sort_tracks(scene):
    obj=rig_store.settings(scene).rig
    if not obj or not obj.animation_data or obj.animation_data.use_tweak_mode:return
    current=playback(obj)
    if current and obj.get(READY):obj[TRACK]=current.name
    for track in list(obj.animation_data.nla_tracks):
        strips=list(track.strips)
        if not strips or not all(nla_motion.owned(obj,s) for s in strips):continue
        if [s.frame_start for s in strips]==sorted(s.frame_start for s in strips):continue
        # Preserve customized strip modifier data rather than deleting it.
        if any(s.modifiers or any(c.modifiers for c in s.fcurves) for s in strips):continue
        values=sorted((descriptor(s) for s in strips),key=lambda v:(v['start'],v['end']))
        for strip in strips:track.strips.remove(strip)
        for value in values:append(obj,track,value)
    authoring_prefix(scene,obj)
    sync_start_frames(obj,current)
    from . import seam_blend
    seam_blend.sync(scene,obj,current,force=True)


def sync_start_frames(obj,current):
    """Evaluate a moving continuation's first frame above Blender's inclusive old end."""
    animation=obj.animation_data
    old=next((t for t in animation.nla_tracks
              if any(s.name.startswith(nla_motion.START_STRIP) for s in t.strips)),None)
    clips=[s for s in current.strips if nla_motion.owned(obj,s) and not s.mute] if current and not current.mute else []
    desired=[]
    for previous,clip in zip(clips,clips[1:]):
        if previous.frame_end!=clip.frame_start or not clip.action.get(nla_motion.MOVING_START):continue
        if (clip.use_reverse or clip.use_animated_time or clip.use_animated_influence or clip.modifiers
                or clip.blend_type!='REPLACE' or clip.blend_in or clip.blend_out):continue
        end=min(clip.frame_start+1,clip.frame_end)
        desired.append((clip.action,clip.action_slot,clip.frame_start,end,clip.action_frame_start,clip.scale))
    def signature(layer):
        return [(s.action,s.action_slot,s.frame_start,s.frame_end,s.action_frame_start,s.scale) for s in layer.strips]
    if old and desired and signature(old)==desired:
        order=list(animation.nla_tracks)
        if order.index(old)==order.index(current)+1:return
    if not desired:
        if old:animation.nla_tracks.remove(old)
        return
    layer=animation.nla_tracks.new(prev=current)
    try:
        layer.name=nla_motion.START_STRIP+'s'
        for action,slot,start,end,action_start,scale in desired:
            strip=layer.strips.new(nla_motion.START_STRIP,math.floor(start),action)
            strip.action_slot=slot
            strip.action_frame_start=action_start
            strip.action_frame_end=action_start+(end-start)/scale
            strip.scale=scale
            strip.frame_start_raw=start;strip.frame_end_raw=end
            strip.blend_type='REPLACE';strip.extrapolation='NOTHING';strip.select=False
        layer.lock=True
    except Exception:
        animation.nla_tracks.remove(layer)
        raise
    if old:animation.nla_tracks.remove(old)
    animation.nla_tracks.active=current
    obj.update_tag(refresh={'OBJECT'})


def predecessor(obj,start,excluded):
    track=playback(obj)
    if track is None or track.mute:return None
    candidates=[strip for strip in track.strips if nla_motion.owned(obj,strip) and not strip.mute
                and not strip.action.get(nla_motion.REQUEST) and strip.action.get('toyxyz_block_uid') not in excluded
                and strip.frame_end<=start+.0001]
    return (track,max(candidates,key=lambda s:s.frame_end)) if candidates else None


def sample(context,obj,item,times,include_user=False,*,read_pose=None):
    """Evaluate the selected native strip alone, restoring every temporary NLA setting."""
    from . import rig,block_links,correction_bounds
    read_pose=read_pose or rig.snapshot
    scene=context.scene;ad=obj.animation_data;track,strip=item
    saved=(ad.use_nla,ad.action_influence,scene.frame_current,scene.frame_subframe)
    tracks=[(t,t.mute,t.is_solo) for t in ad.nla_tracks]
    bounds_track=correction_bounds.track(obj) if include_user else None
    if bounds_track and (bounds_track.mute or bounds_track.strips[0].mute):bounds_track=None
    clips=[(s,s.mute) for t in ad.nla_tracks for s in t.strips]
    bounds_strip=bounds_track.strips[0] if bounds_track else None
    start=strip.frame_start
    neighbor=next((s for s in track.strips if s!=strip and s.frame_end==start),None)
    influence=(strip.use_animated_influence,strip.influence)
    extrapolation=strip.extrapolation
    modes={bone.name:bone.rotation_mode for bone in obj.pose.bones}
    authored=json.loads(strip.action.get('toyxyz_rotation_modes','{}'))
    if not authored:
        paths={fc.data_path for layer in strip.action.layers for key_strip in layer.strips if key_strip.type=='KEYFRAME'
               for bag in key_strip.channelbags if bag.slot_handle==strip.action_slot.handle for fc in bag.fcurves}
        for bone in obj.pose.bones:
            if bone.path_from_id('rotation_quaternion') in paths:authored[bone.name]='QUATERNION'
            elif bone.path_from_id('rotation_axis_angle') in paths:authored[bone.name]='AXIS_ANGLE'
            elif bone.path_from_id('rotation_euler') in paths:authored[bone.name]=bone.rotation_mode if len(bone.rotation_mode)==3 else 'XYZ'
    result=[]
    from . import unified
    with unified.suspend(),block_links.transaction(scene):
        try:
            ad.use_nla=True;ad.action_influence=1 if include_user else 0
            for t,_,_ in tracks:t.mute=t!=track and t!=bounds_track;t.is_solo=False
            for s,_ in clips:s.mute=s!=strip and s!=bounds_strip
            # Blender can choose the outgoing strip at the shared start even when it is muted.
            # Move only its temporary end so the selected strip samples at its exact start.
            if neighbor is not None:neighbor.frame_end_raw=(neighbor.frame_start+start)*.5
            strip.use_animated_influence=False;strip.influence=1
            strip.extrapolation='HOLD'
            for name,mode in authored.items():
                if name in obj.pose.bones:obj.pose.bones[name].rotation_mode=mode
            for at in times:
                at=max(at,start)
                whole=math.floor(at);scene.frame_set(whole,subframe=at-whole);context.view_layer.update()
                result.append(read_pose(context,obj))
        finally:
            if neighbor is not None:neighbor.frame_end_raw=start
            strip.use_animated_influence=influence[0];strip.influence=influence[1]
            strip.extrapolation=extrapolation
            for t,mute,solo in tracks:t.mute=mute;t.is_solo=solo
            for s,mute in clips:s.mute=mute
            for name,mode in modes.items():obj.pose.bones[name].rotation_mode=mode
            ad.use_nla=saved[0];ad.action_influence=saved[1]
            scene.frame_set(saved[2],subframe=saved[3]);context.view_layer.update()
    return result
