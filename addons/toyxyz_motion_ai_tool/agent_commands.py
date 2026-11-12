"""Structured commands executed in the open Blender scene."""

from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

from . import (
    client, control_layers, control_rig, final_motion, keyframes, model_limits, object_constraints,
    pose_constraints, pose_preview, rig, rig_store, timeline,
)


def integer(value, name, minimum=-1000000, maximum=1000000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer from {minimum} to {maximum}.')
    return value


def number(value, name, minimum=-1000000, maximum=1000000):
    if type(value) not in (int, float) or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be a number from {minimum} to {maximum}.')
    return float(value)


def vector(value, name, size=3):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f'{name} must contain {size} numbers.')
    return Vector(tuple(number(item, name) for item in value))


def quaternion(value):
    result = Quaternion(vector(value, 'rotation', 4))
    if result.magnitude < 1e-8:
        raise ValueError('Rotation must be a nonzero [w, x, y, z] quaternion.')
    return result.normalized()


def string(value, name, limit=4096):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
        raise ValueError(f'{name} must be nonempty text of at most {limit} characters.')
    return value


def boolean(value, name):
    if type(value) is not bool:
        raise ValueError(f'{name} must be true or false.')
    return value


def actor_data(context, actor=None, *, edit=False):
    scene = context.scene
    if actor is None:
        settings = rig_store.settings(scene)
    else:
        settings = rig_store.job(scene, actor)
        if settings is None:
            settings = next((entry.data for entry in rig_store.entries(scene) if entry.rig.name == actor), None)
    obj = rig.validate_rig(settings.rig if settings else None)
    if context.view_layer.objects.get(obj.name) != obj or obj.mode not in {'OBJECT', 'POSE'}:
        raise ValueError('The SOMA actor must be in Object or Pose Mode in this view layer.')
    if edit and (not obj.is_editable or rig_store.deletion_busy(obj)):
        raise ValueError('The SOMA actor is read-only or its generation is still in progress.')
    return settings


def block_for(settings, block):
    item = next((item for item in settings.blocks if item.uid == block), None)
    if item is None:
        raise ValueError('Unknown block ID for this actor. Use status to list its blocks.')
    return item


def block_info(block):
    return dict(id=block.uid, name=block.name, start=block.start, end=block.end, model=block.engine,
                prompt=block.prompt, enabled=block.enabled, selected=block.selected, has_result=block.has_result,
                curve=block.path_curve.name if block.path_curve else None, curve_start=block.path_start_percent)


def job_info(scene):
    state = client.state
    if state['scene_uid'] != rig_store.master(scene).scene_uid:
        return dict(connected=False, status='', progress=None, busy=False)
    return dict(connected=state['connected'], status=state['job_status'], progress=state.get('progress'),
                stage=state.get('progress_stage'), message=state['message'], id=state.get('job_id'),
                actor=(state.get('pending_connect') or {}).get('rig_uuid') or state.get('input_uuid'),
                busy=bool(state.get('sequence') or state.get('pending_connect') or state.get('auto_apply_pending')
                          or state['job_status'] in ('queued', 'running', 'connecting')),
                application_error=bool(state.get('auto_apply_error')))


def status(context):
    scene = context.scene
    selected = rig_store.settings(scene).rig
    actors = []
    for entry in rig_store.entries(scene):
        obj = entry.rig
        actors.append(dict(id=obj['toyxyz_uuid'], name=obj.name, selected=obj == selected,
                           control_rig=control_rig.enabled(obj), location=list(obj.matrix_world.translation),
                           blocks=[block_info(block) for block in entry.data.blocks],
                           pose_keys=list(keyframes.frames(obj, force=True, model_only=True)),
                           constraints=object_constraints.definitions(entry.data)))
    return dict(scene=scene.name, file=bpy.data.filepath, frame=scene.frame_current, fps=timeline.fps(scene),
                actors=actors, curves=[obj.name for obj in scene.objects if obj.type == 'CURVE'], job=job_info(scene))


def actor_add(context, controls=False):
    boolean(controls, 'controls')
    if bpy.ops.toyxyz_motion_ai_tool.add_soma() != {'FINISHED'}:
        raise ValueError('Could not add a SOMA actor.')
    obj = rig_store.settings(context.scene).rig
    if controls:
        control_rig.setup(context, obj)
    return dict(id=obj['toyxyz_uuid'], name=obj.name)


def actor_place(context, location, actor=None, rotation=None):
    obj = actor_data(context, actor, edit=True).rig
    position = vector(location, 'location')
    current = obj.matrix_world
    if rotation is None:
        result = current.copy()
        result.translation = position
    else:
        result = Matrix.LocRotScale(position, quaternion(rotation), current.to_scale())
    obj.matrix_world = result
    context.view_layer.update()
    return dict(location=list(obj.matrix_world.translation))


def block_change(context, block=None, actor=None, start=None, end=None, model=None, prompt=None, enabled=None):
    settings = actor_data(context, actor, edit=True)
    current = block_for(settings, block) if block is not None else None
    if prompt is not None and (not isinstance(prompt, str) or len(prompt) > 4000 or '\x00' in prompt):
        raise ValueError('prompt must be text of at most 4000 characters.')
    if enabled is not None:
        boolean(enabled, 'enabled')
    if model is None:
        focused = current or timeline.active(settings)
        model = focused.engine if focused else settings.engine
    if not isinstance(model, str) or model not in model_limits.LIMITS:
        raise ValueError('model must be ardy, kimodo or motionbricks.')
    fps = timeline.fps(context.scene)
    if start is None:
        start = current.start if current else max((b.end for b in settings.blocks), default=context.scene.frame_current)
    if end is None:
        end = current.end if current else start + model_limits.clamp(model, fps, round(2 * fps))
    start, end = integer(start, 'start'), integer(end, 'end')
    minimum, maximum = model_limits.frames(model, fps)
    if not minimum <= end - start <= maximum:
        raise ValueError(f'{model} requires {minimum}–{maximum:g} frames at this frame rate.')
    is_enabled = current.enabled if current else True
    if enabled is not None:
        is_enabled = enabled
    if is_enabled and any(
        other != current and other.enabled and other.start < end and start < other.end for other in settings.blocks
    ):
        raise ValueError('This range overlaps an enabled motion block.')
    with rig_store.use(context.scene, settings):
        if current is None:
            control_layers.deselect(context, settings)
            current = timeline.add(context.scene)
        if current.engine != model:
            current.engine = model
        timeline.set_range(current, start, end)
        if prompt is not None:
            current.prompt = prompt
        if enabled is not None:
            current.enabled = enabled
    return block_info(current)


def block_update(context, block, **args):
    return block_change(context, block=string(block, 'block ID'), **args)


def block_add(context, **args):
    return block_change(context, block=None, **args)


def frame_set(context, frame):
    context.scene.frame_set(integer(frame, 'frame'))
    return dict(frame=frame)


def pose_get(context, actor=None):
    obj = actor_data(context, actor).rig
    evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
    bones = {}
    for name in control_rig.names(obj):
        bone = evaluated.pose.bones[name]
        bones[name] = dict(rotation=list(bone.matrix_basis.to_quaternion()), location=list(bone.location),
                           world_position=list(evaluated.matrix_world @ bone.head))
    return dict(frame=context.scene.frame_current, controls=bones,
                joints={name: list(evaluated.matrix_world @ evaluated.pose.bones[name].head) for name in rig.NAMES},
                ik={name: bool(evaluated.pose.bones[limb['target']]['ik']) for name, limb in control_rig.LIMBS.items()}
                if control_rig.enabled(obj) else {})


def pose_key(context, frame, actor=None, bones=None, root_position=None, constraint=None):
    obj = actor_data(context, actor, edit=True).rig
    at = integer(frame, 'frame')
    if obj.animation_data and obj.animation_data.use_tweak_mode:
        raise ValueError('Exit NLA Tweak Mode before keying the actor’s main Action.')
    root = vector(root_position, 'root_position') if root_position is not None else None
    if bones is None:
        bones = {}
    if not isinstance(bones, dict) or (not bones and root is None):
        raise ValueError('Supply bone transforms or a world-space root_position.')
    if constraint is not None:
        constraint = pose_constraints.normalize(string(constraint, 'constraint', 128))
    allowed = set(control_rig.names(obj))
    controls = control_rig.enabled(obj)
    hips_name = control_rig.fk('Hips') if controls else 'Hips'
    edits = {}
    for name, transform in bones.items():
        name = control_rig.fk(name) if controls and name in rig.NAMES else name
        if name not in allowed or name in edits or not isinstance(transform, dict) or not transform.keys() <= {'rotation', 'location'}:
            raise ValueError(f'Invalid, duplicate or unsupported transform for {name}.')
        q = quaternion(transform['rotation']) if 'rotation' in transform else None
        location = vector(transform['location'], 'location') if 'location' in transform else None
        if q is not None and name.startswith('Pole_'):
            raise ValueError('A pole supports location only.')
        if location is not None and name != hips_name and not name.startswith(('IK_', 'Pole_')) and name != control_rig.MASTER:
            raise ValueError(f'{name} supports rotation only.')
        edits[name] = (q, location)
    if root is not None:
        q, local = edits.get(hips_name, (None, None))
        if local is not None:
            raise ValueError('Use either world root_position or local Hips location.')
        edits[hips_name] = (q, None)
    action, slot = rig.pose_action(obj)
    paths = {obj.pose.bones[name].path_from_id(channel) for name in edits
             for channel in ('location', control_rig.rotation_channel(obj.pose.bones[name]))}
    if action and (not action.is_editable or any((curve.lock or (curve.group and curve.group.lock)) and curve.data_path in paths
                                                for curve in control_rig.action_curves(action, slot))):
        raise ValueError('Make the Action local and unlock its pose curves first.')
    if constraint is not None and not edits.keys() & set(control_rig.names(obj, model_only=True)):
        raise ValueError('A generation constraint requires a body pose key.')
    from . import unified
    animation = obj.animation_data
    if animation and animation.action != action:
        raise ValueError('Activate the user pose Action before keying the actor.')
    scene = context.scene
    original_frame = scene.frame_current, scene.frame_subframe
    original_pose = rig.pose_state(obj)
    backup = None
    writing = False
    try:
        scene.frame_set(at)
        local_root = obj.matrix_world.inverted() @ root if root is not None else None
        if controls:
            evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
            for limb in control_rig.LIMBS.values():
                if evaluated.pose.bones[limb['target']]['ik'] and edits.keys() & {control_rig.fk(name) for name in limb['bones']}:
                    raise ValueError(f'Use {limb["target"]} and {limb["pole"]} while this limb is in IK.')
        if action:
            backup = action.copy()
        writing = True
        write_pose_keys(context, obj, at, edits, hips_name, local_root)
        keyframes.clear()
        if constraint is not None:
            pose_constraints.set_kind(obj, at, constraint)
        pose_preview.changed()
        scene.frame_set(at)
        context.view_layer.update()
        return dict(frame=at, controls=list(edits), constraint=pose_constraints.kind(obj, at))
    except BaseException:
        if writing:
            current = obj.animation_data
            new_action = current.action if current and current.action != action else None
            if backup:
                unified.restore_keyframes(action, current.action_slot if current else slot, backup, paths)
                key = pose_constraints.KEY
                if key in backup:action[key] = backup[key]
                elif key in action:del action[key]
            if animation is not None:
                rig.assign_action(obj, action, slot)
            elif current:
                obj.animation_data_clear()
            if new_action and new_action.users == 0:
                bpy.data.actions.remove(new_action)
            keyframes.clear()
        scene.frame_set(original_frame[0], subframe=original_frame[1])
        rig.restore_pose_state(obj, original_pose, only_changed=True)
        context.view_layer.update()
        raise
    finally:
        if backup:bpy.data.actions.remove(backup)


def write_pose_keys(context, obj, at, edits, hips_name, local_root):
    for name, (rotation, location) in edits.items():
        bone = obj.pose.bones[name]
        channel = control_rig.rotation_channel(bone)
        if rotation is not None:
            if channel == 'rotation_euler':
                rotation = rotation.to_euler(bone.rotation_mode, bone.rotation_euler)
            elif channel == 'rotation_axis_angle':
                axis, angle = rotation.to_axis_angle()
                rotation = (angle, *axis)
            setattr(bone, channel, rotation)
        if location is not None:
            bone.location = location
        if local_root is not None and name == hips_name:
            context.view_layer.update()
            basis = bone.matrix.copy()
            basis.translation = local_root
            bone.matrix = basis
        use_location = location is not None or (local_root is not None and name == hips_name) or name.startswith('Pole_')
        control_rig.key_transform(bone, at, use_location)


def limb_switch(context, limb, ik, actor=None):
    obj = actor_data(context, actor, edit=True).rig
    if limb not in control_rig.LIMBS:
        raise ValueError('limb must be LeftArm, RightArm, LeftLeg or RightLeg.')
    control_rig.switch(context, obj, limb, float(boolean(ik, 'ik')))
    return dict(limb=limb, ik=ik, frame=context.scene.frame_current)


def path_set(context, block, actor=None, points=None, curve=None, start_percent=0.):
    settings = actor_data(context, actor, edit=True)
    item = block_for(settings, block)
    percent = number(start_percent, 'start_percent', 0, 100)
    if points is not None and curve is not None:
        raise ValueError('Use either world-space points or an existing curve name.')
    if item.engine == 'motionbricks' and (points is not None or curve):
        raise ValueError('Path curves are available for ARDY and Kimodo blocks.')
    target = None
    if points is not None:
        if not isinstance(points, list) or not 2 <= len(points) <= 512:
            raise ValueError('Supply 2 to 512 curve points.')
        coords = [vector(point, 'path point') for point in points]
        if not any((point.xy - coords[0].xy).length > 1e-5 for point in coords[1:]):
            raise ValueError('The path needs movement in the XY ground plane.')
        data = bpy.data.curves.new(f'{settings.rig.name} {item.name} Path', 'CURVE')
        data.dimensions = '3D'
        spline = data.splines.new('POLY')
        spline.points.add(len(coords) - 1)
        for point, value in zip(spline.points, coords):
            point.co = (*value, 1.)
        target = bpy.data.objects.new(data.name, data)
        context.scene.collection.objects.link(target)
    elif curve is not None:
        target = context.view_layer.objects.get(string(curve, 'curve', 512))
        if target is None or target.type != 'CURVE':
            raise ValueError('Choose a Curve object in this view layer.')
    item.path_curve = target
    item.path_start_percent = percent if target else 0.
    pose_preview.changed()
    return block_info(item)


def constraint_set(context, frame, kind, actor=None, location=None, rotation=None, target=None,
                   root_heading=True, root_height=True):
    settings = actor_data(context, actor, edit=True)
    at = integer(frame, 'frame')
    if not isinstance(kind, str) or kind not in object_constraints.LABELS:
        raise ValueError('Use ROOT, LEFT_HAND, RIGHT_HAND, LEFT_FOOT or RIGHT_FOOT.')
    boolean(root_heading, 'root_heading')
    boolean(root_height, 'root_height')
    if target is not None:
        if location is not None or rotation is not None:
            raise ValueError('Use a target object or supply a world-space transform.')
        obj = context.view_layer.objects.get(string(target, 'target', 512))
        if obj is None or obj == settings.rig or obj in settings.rig.children_recursive:
            raise ValueError('Choose an independent target object in this view layer.')
    else:
        position = vector(location, 'location')
        orientation = quaternion(rotation) if rotation is not None else Quaternion()
        obj = bpy.data.objects.new(f'{settings.rig.name} {kind} {at}', None)
        obj.empty_display_type = 'ARROWS'
        obj.empty_display_size = .12
        context.scene.collection.objects.link(obj)
        obj.rotation_mode = 'QUATERNION'
        obj.rotation_quaternion = orientation
        obj.location = position
    markers = settings.object_constraints
    index = next((i for i, marker in enumerate(markers) if marker.frame == at and marker.kind == kind), None)
    marker = markers.add() if index is None else markers[index]
    marker.frame, marker.kind, marker.target = at, kind, obj
    marker.root_heading, marker.root_height = root_heading, root_height
    return dict(frame=at, kind=kind, target=obj.name, root_heading=root_heading, root_height=root_height)


def generate(context, actor=None, blocks=None):
    settings = actor_data(context, actor)
    with rig_store.use(context.scene, settings):
        if blocks is not None:
            if not isinstance(blocks, list) or not 1 <= len(blocks) <= 32:
                raise ValueError('Supply 1 to 32 block IDs.')
            ids = [block_for(settings, string(block, 'block ID')).uid for block in blocks]
            timeline.selection_set(settings, set(ids))
        if bpy.ops.toyxyz_motion_ai_tool.generate() != {'FINISHED'}:
            raise ValueError(client.state['message'])
    return job_info(context.scene)


def cancel(context):
    if not job_info(context.scene)['busy']:
        raise ValueError('This scene has no active Motion AI generation.')
    bpy.ops.toyxyz_motion_ai_tool.app_control(command='cancel')
    return job_info(context.scene)


def export_fbx(context, filepath, actor=None, overwrite=False):
    obj = actor_data(context, actor).rig
    path = Path(string(filepath, 'filepath'))
    if not path.is_absolute() or path.suffix.lower() != '.fbx':
        raise ValueError('Choose an absolute .fbx path.')
    boolean(overwrite, 'overwrite')
    if path.exists() and not overwrite:
        raise ValueError('The output already exists. Supply overwrite=true to replace it.')
    first, last = final_motion.export_fbx(context, obj, str(path))
    return dict(filepath=str(path), first_frame=first, last_frame=last)


COMMANDS = {
    'status': status,
    'actor.add': actor_add,
    'actor.place': actor_place,
    'frame.set': frame_set,
    'block.add': block_add,
    'block.update': block_update,
    'pose.get': pose_get,
    'pose.key': pose_key,
    'limb.switch': limb_switch,
    'path.set': path_set,
    'constraint.set': constraint_set,
    'generate': generate,
    'cancel': cancel,
    'export.fbx': export_fbx,
}

UNDOABLE = {
    'actor.add', 'actor.place', 'block.add', 'block.update',
    'pose.key', 'limb.switch', 'path.set', 'constraint.set',
}
READ_ONLY = {'status', 'pose.get'}


def run(context, command, args):
    if command not in COMMANDS:
        raise ValueError(f'Unknown command {command!r}.')
    if command not in READ_ONLY | {'cancel'} and (context.screen.is_animation_playing or pose_preview.interacting(context)):
        raise ValueError('Finish the current Blender edit or stop playback before sending this command.')
    result = COMMANDS[command](context, **args)
    if command in UNDOABLE or command == 'frame.set':
        timeline.redraw_regions(context.scene, context.window_manager.windows)
    return result
