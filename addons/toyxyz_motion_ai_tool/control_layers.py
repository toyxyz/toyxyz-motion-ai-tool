"""Per-actor native NLA correction layers and their editing session."""
from contextlib import contextmanager
import json
import bpy
from . import rig

OWNER = 'toyxyz_control_layer_for'
BASE = 'Motion AI · Layer Base'
DEFAULTS = 'toyxyz_control_layer_defaults'


def rows(obj):
    ad = obj.animation_data if obj else None
    if not ad:
        return []
    owner = obj.get('toyxyz_uuid')
    return [(track, strip) for track in ad.nla_tracks for strip in track.strips
            if strip.action and owner and strip.action.get(OWNER) == owner]


def editing(obj):
    ad = obj.animation_data if obj else None
    if not (ad and ad.use_tweak_mode and ad.action and ad.action.get(OWNER) == obj.get('toyxyz_uuid')):
        return None
    return next((item for item in rows(obj) if item[1].action == ad.action), None)


def new_lower_track(obj):
    """Keep generated playback and its guards below the authored layers."""
    tracks = obj.animation_data.nla_tracks
    layers = rows(obj)
    if not layers:
        return tracks.new()
    order = list(tracks)
    index = order.index(layers[0][0])
    if index == 0:
        raise ValueError('Restore the empty Motion AI · Layer Base NLA track before generating.')
    return tracks.new(prev=order[index-1])


def refresh(context, obj):
    from . import keyframes, scene_sampling, timeline
    keyframes.clear()
    scene = context.scene
    obj.update_tag(refresh={'OBJECT'})
    scene_sampling.publish(context, obj)
    timeline.redraw_regions(scene, context.window_manager.windows)


def leave(obj, context=None):
    if editing(obj):
        if context is not None and context.screen:
            with _nla_context(context, obj):
                if bpy.ops.nla.tweakmode_exit.poll():
                    bpy.ops.nla.tweakmode_exit()
        if editing(obj):
            obj.animation_data.use_tweak_mode = False
        return True
    return False


def deselect(context, settings):
    if leave(settings.rig, context):
        refresh(context, settings.rig)
    if settings.selection == 'LAYER':
        settings.selection = 'BLOCK'


def _active_strip(ad, item):
    track, strip = item
    ad.nla_tracks.active = track
    track.select = True
    for other in track.strips:
        other.select = other == strip


@contextmanager
def _nla_context(context, obj):
    """Scope the native operator to the actor without retaining an NLA editor."""
    areas = context.screen.areas
    area = (next((area for area in areas if area.type == 'NLA_EDITOR'), None)
            or next((area for area in areas if area.type == 'DOPESHEET_EDITOR'), None)
            or next((area for area in areas if area != context.area), None)
            or context.area or areas[0])
    old_type, old_ui = area.type, area.ui_type
    layer = context.view_layer
    previous = list(context.selected_objects)
    try:
        if old_type != 'NLA_EDITOR':
            area.type = 'NLA_EDITOR'
        dope = area.spaces.active.dopesheet
        old_selected, old_filter, old_collection = dope.show_only_selected, dope.filter_text, dope.filter_collection
        try:
            dope.show_only_selected = True
            dope.filter_text = ''
            dope.filter_collection = None
            for other in previous:
                if other != obj:
                    other.select_set(False, view_layer=layer)
            obj.select_set(True, view_layer=layer)
            with context.temp_override(area=area):
                yield
        finally:
            dope.show_only_selected, dope.filter_text, dope.filter_collection = old_selected, old_filter, old_collection
            for other in previous:
                other.select_set(True, view_layer=layer)
            if obj not in previous:
                obj.select_set(False, view_layer=layer)
    finally:
        if old_type != 'NLA_EDITOR':
            area.type = old_type
            if area.ui_type != old_ui:
                area.ui_type = old_ui


def select(context, settings, item):
    from . import rig_store
    obj = settings.rig
    ad = obj.animation_data
    if obj.mode == 'EDIT' or not obj.visible_get(view_layer=context.view_layer):
        raise ValueError('Select a visible SOMA actor in Object or Pose Mode.')
    previous = editing(obj)
    if ad.use_tweak_mode and not previous:
        raise ValueError('Exit the current NLA edit before selecting a Control Layer.')
    if context.view_layer.objects.active != obj:
        rig_store.select(context.scene, obj, context)
    leave(obj, context)
    try:
        _active_strip(ad, item)
        with _nla_context(context, obj):
            status = bpy.ops.nla.tweakmode_enter(use_upper_stack_evaluation=True)
        if status != {'FINISHED'} or editing(obj) != item:
            raise ValueError('Blender could not open this Control Layer for editing.')
    except (ValueError, RuntimeError) as exc:
        leave(obj, context)
        if previous:
            _active_strip(ad, previous)
            ad.use_tweak_mode = True
        raise ValueError(str(exc)) from exc
    settings.selection = 'LAYER'
    refresh(context, obj)


def add(context, settings, start, end):
    from . import unified
    obj = rig.validate_rig(settings.rig)
    ad = obj.animation_data_create()
    previous = editing(obj)
    if ad.use_tweak_mode and not previous:
        raise ValueError('Exit the current NLA edit before adding a Control Layer.')
    leave(obj, context)
    tracks = ad.nla_tracks
    base = None
    action = None
    track = None
    try:
        unified.enable(context, obj)
        if DEFAULTS not in obj:
            obj[DEFAULTS] = json.dumps(rig.pose_state(obj))
        if not rows(obj) and tracks.get(BASE) is None:
            base = tracks.new()
            base.name = BASE
            base.lock = True
        names = {strip.name for _, strip in rows(obj)}
        index = 1
        while f'Control Layer {index}' in names:
            index += 1
        name = f'Control Layer {index}'
        action = bpy.data.actions.new(name)
        action[OWNER] = obj['toyxyz_uuid']
        action[unified.OFFSETS] = True
        action.use_frame_range = True
        action.frame_start = start
        action.frame_end = end
        slot = action.slots.new(id_type='OBJECT', name=obj.name)
        unified.channelbag(action, slot)
        track = tracks.new()
        track.name = name
        strip = track.strips.new(name, start, action)
        strip.action_slot = slot
        strip.blend_type = 'COMBINE'
        strip.extrapolation = 'NOTHING'
        strip.use_auto_blend = False
        strip.use_sync_length = False
        select(context, settings, (track, strip))
        return track, strip
    except (ValueError, RuntimeError) as exc:
        leave(obj, context)
        if track is not None:
            tracks.remove(track)
        if base is not None:
            tracks.remove(base)
            if DEFAULTS in obj:
                del obj[DEFAULTS]
        if action is not None and action.users == 0:
            bpy.data.actions.remove(action)
        if previous:
            _active_strip(ad, previous)
            ad.use_tweak_mode = True
        raise ValueError(str(exc)) from exc


def place(strip, start, end):
    strip.frame_start_raw = start
    strip.frame_end_raw = end


def resize(strip, start, end, source_start, source_scale, source_frame):
    """Trim or extend playback while keeping each key at its existing scene frame."""
    action_start = source_start + (start-source_frame)/source_scale
    action_end = source_start + (end-source_frame)/source_scale
    # Set a non-overlapping pair even when the new interval crosses the old one.
    if action_start >= strip.action_frame_end:
        strip.action_frame_end = action_end
    strip.action_frame_start = action_start
    strip.action_frame_end = action_end
    strip.scale = source_scale
    strip.frame_start_raw = start
    strip.frame_end_raw = end


def _reset_channels(obj, items):
    """Restore the input for channels which may have no other animation."""
    from . import control_rig
    paths = {curve.data_path for _, strip in items
             for curve in control_rig.action_curves(strip.action, strip.action_slot)
             if curve.keyframe_points or curve.sampled_points}
    if not paths:
        return
    defaults = json.loads(obj.get(DEFAULTS, '{}'))
    for name, values in defaults.items():
        bone = obj.pose.bones.get(name)
        if bone:
            for channel in rig.TRANSFORM_CHANNELS:
                if bone.path_from_id(channel) in paths:
                    setattr(bone, channel, values[channel])


def toggle(context, settings, item):
    track, _ = item
    track.mute = not track.mute
    if track.mute:
        _reset_channels(settings.rig, [item])
    refresh(context, settings.rig)


def delete(context, settings):
    obj = settings.rig
    item = editing(obj)
    if not item:
        raise ValueError('Select a Control Layer to delete.')
    track, strip = item
    action = strip.action
    leave(obj, context)
    tracks = obj.animation_data.nla_tracks
    _reset_channels(obj, [item])
    track.strips.remove(strip)
    if not track.strips:
        tracks.remove(track)
    if action.users == 0 and not action.use_fake_user:
        bpy.data.actions.remove(action)
    base = tracks.get(BASE)
    if not rows(obj):
        if base and not base.strips:
            tracks.remove(base)
        if DEFAULTS in obj:
            del obj[DEFAULTS]
    settings.selection = 'BLOCK'
    refresh(context, obj)


@contextmanager
def without_layers(context, obj, *, preserve_pose=False):
    """Keep the correction stack out of model inputs and generated base baking."""
    items = rows(obj)
    if not items:
        yield
        return
    ad = obj.animation_data
    active = editing(obj)
    muted = [(track, track.mute) for track, _ in items]
    if not active and all(was_muted for _, was_muted in muted):
        yield
        return
    pose = rig.pose_state(obj) if preserve_pose else None
    leave(obj)
    try:
        for track, was_muted in muted:
            if not was_muted:
                track.mute = True
        _reset_channels(obj, items)
        yield
    finally:
        for track, was_muted in muted:
            if track.mute != was_muted:
                track.mute = was_muted
        if active:
            _active_strip(ad, active)
            ad.use_tweak_mode = True
        scene = context.scene
        scene.frame_set(scene.frame_current, subframe=scene.frame_subframe)
        if pose is not None:
            rig.restore_pose_state(obj, pose, only_changed=True)
        context.view_layer.update()


