"""Authoring blocks and tool-owned native NLA strips share persistent block IDs."""
from . import rig_store
from contextlib import contextmanager
import bpy
from bpy.app.handlers import persistent
from . import nla_motion,model_limits

UID='toyxyz_block_uid'
LINKED='toyxyz_linked_block'
_busy=False
_state={}


def busy():return _busy
@persistent
def clear(*_):_state.clear()


def blocks(scene):return {b.uid:b for b in rig_store.settings(scene).blocks if b.uid}


def items(scene):
    obj=rig_store.settings(scene).rig
    return [(track,strip) for track,strip in nla_motion.strips(obj) if not strip.action.get(nla_motion.REQUEST)]


def snapshot(scene):
    from . import continuity
    current=continuity.playback(rig_store.settings(scene).rig)
    return dict(blocks={uid:(b.start,b.end,b.name,b.engine,b.enabled) for uid,b in blocks(scene).items()},
                strips={strip.as_pointer():(strip.action.get(UID),round(strip.frame_start,5),round(strip.frame_end,5),strip.name,strip.mute)
                        for _,strip in items(scene)},
                playback={strip.action.get(UID):strip.as_pointer() for track,strip in items(scene) if track==current})


def state_key(scene):
    obj=rig_store.settings(scene).rig
    return scene.as_pointer(),obj.as_pointer() if obj else 0


def reset(scene):_state[state_key(scene)]=snapshot(scene)


@contextmanager
def transaction(scene):
    global _busy
    previous=_busy;_busy=True
    try:yield
    finally:
        try:
            if not previous:
                from . import continuity
                continuity.sort_tracks(scene)
        finally:
            _busy=previous
            if not previous:reset(scene)


def linked(scene,uid):return [(track,strip) for track,strip in items(scene) if strip.action.get(UID)==uid]


def empty_preview(scene):
    obj=rig_store.settings(scene).rig
    if not obj or not obj.animation_data or items(scene):return
    if obj.get('toyxyz_nla_preview'):
        obj.animation_data.action_influence=float(obj.get('toyxyz_author_influence',1))
        obj['toyxyz_nla_preview']=False
        obj.animation_data.use_nla=any(track.strips for track in obj.animation_data.nla_tracks)


def remove_uid(scene,uid):
    obj=rig_store.settings(scene).rig
    for track,strip in list(linked(scene,uid)):
        track.strips.remove(strip)
        if not track.strips:obj.animation_data.nla_tracks.remove(track)
    empty_preview(scene)


def delete(scene,index):
    s=rig_store.settings(scene)
    if not s.blocks:return
    index=min(max(0,index),len(s.blocks)-1)
    if s.rig and s.rig.animation_data and s.rig.animation_data.use_tweak_mode:
        raise ValueError('Exit NLA Tweak Mode before deleting a linked motion block.')
    with transaction(scene):
        remove_uid(scene,s.blocks[index].uid);s.blocks.remove(index)
        from . import timeline
        timeline.focus(s,index)


def delete_selected(scene):
    from . import timeline
    s=rig_store.settings(scene)
    indices=[i for i,b in enumerate(s.blocks) if b.selected]
    if not indices:raise ValueError('Select motion blocks to delete.')
    if s.rig and s.rig.animation_data and s.rig.animation_data.use_tweak_mode:
        raise ValueError('Exit NLA Tweak Mode before deleting linked motion blocks.')
    with transaction(scene):
        for index in reversed(indices):
            remove_uid(scene,s.blocks[index].uid);s.blocks.remove(index)
        remaining=[i for i,b in enumerate(s.blocks) if b.selected]
        timeline.focus(s,remaining[-1] if remaining else min(indices[0],len(s.blocks)-1))


def rehome(scene,track,strip):
    """Separate an overlapping legacy strip while retaining its native animation."""
    # RNA exposes no modifier-copy API for NLA strips. Keep customized data on
    # its original strip instead of losing it during a temporary overlap.
    if strip.modifiers or any(curve.modifiers for curve in strip.fcurves):return track,strip
    obj=rig_store.settings(scene).rig;ad=obj.animation_data
    target=ad.nla_tracks.new(prev=track);target.name=track.name+' · '+strip.name
    for name in ('mute','is_solo','lock','select'):setattr(target,name,getattr(track,name))
    action=strip.action;slot=strip.action_slot
    copy=nla_motion.create_strip(obj,target,action,slot,strip.frame_start,strip.frame_end,strip.name)
    for name in ('action_frame_start','action_frame_end','repeat','scale','blend_type','extrapolation',
                 'influence','mute','use_auto_blend','blend_in','blend_out','use_reverse','use_sync_length'):
        setattr(copy,name,getattr(strip,name))
    # Native generated strips are normally unanimated, but preserve edited strip curves too.
    for fc in strip.fcurves:
        if fc.data_path=='influence':copy.use_animated_influence=True
        elif fc.data_path=='strip_time':copy.use_animated_time=True
        for point in fc.keyframe_points:
            setattr(copy,fc.data_path,point.co.y);copy.keyframe_insert(data_path=fc.data_path,frame=point.co.x)
        other=next((curve for curve in copy.fcurves if curve.data_path==fc.data_path),None)
        if other:
            other.extrapolation=fc.extrapolation;other.auto_smoothing=fc.auto_smoothing;other.mute=fc.mute
            for old,new in zip(fc.keyframe_points,other.keyframe_points):
                new.interpolation=old.interpolation;new.handle_left_type=old.handle_left_type;new.handle_right_type=old.handle_right_type
                new.handle_left=old.handle_left;new.handle_right=old.handle_right
    track.strips.remove(strip)
    if not track.strips:ad.nla_tracks.remove(track)
    return target,copy


def obj_is_managed_snapshot(scene,track):
    from . import continuity
    obj=rig_store.settings(scene).rig
    return track==continuity.playback(obj) or track.mute


def push_range(scene,block):
    groups={}
    for track,strip in linked(scene,block.uid):groups.setdefault(track.as_pointer(),[]).append((track,strip))
    if groups:block.has_result=True
    for group in groups.values():
        low=min(strip.frame_start for _,strip in group);high=max(strip.frame_end for _,strip in group)
        factor=(block.end-block.start)/max(.001,high-low)
        for track,strip in group:
            start=block.start+(strip.frame_start-low)*factor;end=block.start+(strip.frame_end-low)*factor
            if not obj_is_managed_snapshot(scene,track) and any(other!=strip and other.action and other.action.get(UID)!=block.uid and other.frame_start<end-.001 and other.frame_end>start+.001 for other in track.strips):
                track,strip=rehome(scene,track,strip)
            strip.scale=(end-start)/max(.001,(strip.action_frame_end-strip.action_frame_start)*strip.repeat)
            strip.frame_start_raw=start;strip.frame_end_raw=end;strip.name=block.name
            was_linked=bool(strip.action.get(LINKED));strip.action[LINKED]=True
            strip.action['toyxyz_block_enabled']=block.enabled
            before=_state.get(state_key(scene),{}).get('blocks',{}).get(block.uid)
            if (not was_linked) or (before and before[4]!=block.enabled):strip.mute=not block.enabled


def push(scene,uid):
    if _busy:return
    block=blocks(scene).get(uid)
    if block is None:return
    obj=rig_store.settings(scene).rig
    if obj and obj.animation_data and obj.animation_data.use_tweak_mode:return
    with transaction(scene):push_range(scene,block)


def recover(scene):
    """Restore a block returned by native NLA undo, without adopting unrelated Actions."""
    from . import timeline
    s=rig_store.settings(scene);known=blocks(scene)
    with transaction(scene):
        from . import continuity
        current=continuity.playback(s.rig)
        present={strip.action.get(UID) for track,strip in items(scene) if track==current or not track.mute}
        for index in reversed(range(len(s.blocks))):
            block=s.blocks[index]
            if block.has_result and block.uid not in present:
                remove_uid(scene,block.uid);s.blocks.remove(index)
        known=blocks(scene)
        for _,strip in items(scene):
            action=strip.action;uid=action.get(UID)
            if not uid or uid in known:continue
            if not action.get(LINKED):continue
            block=s.blocks.add();block.uid=uid;block.engine=action.get(nla_motion.ENGINE,'kimodo')
            block.name=strip.name;block.prompt=action.get(nla_motion.PROMPT,'')
            block.enabled=action.get('toyxyz_block_enabled',True)
            block.has_result=True
            timeline.set_range(block,strip.frame_start,strip.frame_end);known[uid]=block
        for uid,block in known.items():
            matches=linked(scene,uid)
            for _,strip in matches:strip.action[LINKED]=True;block.has_result=True
            if matches:
                # Native undo/redo can restore strip edits before the timer's PG
                # update was captured. Recover authoring timing from native data.
                track=matches[-1][0];group=[strip for parent,strip in matches if parent==track]
                start=round(min(strip.frame_start for strip in group));end=round(max(strip.frame_end for strip in group))
                duration=model_limits.clamp(block.engine,scene.render.fps/scene.render.fps_base,end-start)
                timeline.set_range(block,start,start+duration);block.name=matches[-1][1].name
                push_range(scene,block)
        timeline.focus(s,s.active_block)
        empty_preview(scene)


def sync(scene):
    """Detect native NLA edits; no frame sampling or Python pose playback."""
    if _busy:return
    obj=rig_store.settings(scene).rig
    if obj and obj.animation_data and obj.animation_data.use_tweak_mode:return
    previous=_state.get(state_key(scene))
    if previous is None:recover(scene);return
    current=snapshot(scene)
    if current==previous:return
    from . import timeline
    with transaction(scene):
        known=blocks(scene)
        for uid in previous['blocks'].keys()-known.keys():remove_uid(scene,uid)
        for uid,block in list(known.items()):
            before=previous['blocks'].get(uid)
            if before is None or current['blocks'][uid]!=before:
                push_range(scene,block);continue
            old={pointer:value for pointer,value in previous['strips'].items() if value[0]==uid}
            now=[(track,strip) for track,strip in linked(scene,uid)]
            active_pointer=previous.get('playback',{}).get(uid)
            active_deleted=active_pointer is not None and active_pointer not in current['strips']
            if (old and not now) or active_deleted:
                remove_uid(scene,uid)
                index=next(i for i,b in enumerate(rig_store.settings(scene).blocks) if b.uid==uid)
                s=rig_store.settings(scene);s.blocks.remove(index);timeline.focus(s,s.active_block);continue
            changed=[(track,strip) for track,strip in now if strip.as_pointer() in old and
                     (round(strip.frame_start,5),round(strip.frame_end,5),strip.name)!=old[strip.as_pointer()][1:4]]
            if changed:
                track,strip=changed[-1]
                group=[other for t,other in now if t==track]
                start=round(min(other.frame_start for other in group));end=round(max(other.frame_end for other in group))
                duration=model_limits.clamp(block.engine,scene.render.fps/scene.render.fps_base,end-start)
                timeline.set_range(block,start,start+duration);block.name=strip.name
                push_range(scene,block)
        empty_preview(scene)


def register():
    clear()
    for handlers in (bpy.app.handlers.undo_post,bpy.app.handlers.redo_post,bpy.app.handlers.load_post):
        if clear not in handlers:handlers.append(clear)


def unregister():
    clear()
    for handlers in (bpy.app.handlers.undo_post,bpy.app.handlers.redo_post,bpy.app.handlers.load_post):
        if clear in handlers:handlers.remove(clear)
