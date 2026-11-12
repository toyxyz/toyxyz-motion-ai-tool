"""Export evaluated actor motion on a temporary SOMA skeleton."""
from array import array
from contextlib import contextmanager
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ExportHelper
from mathutils import Matrix

from . import control_rig, nla_motion, pose_edit, pose_preview, rig, rig_store


CHANNELS = ('location', 'rotation_quaternion', 'scale')


def actor_for(context, uid=''):
    if not context.scene:
        return None
    if uid:
        settings = rig_store.job(context.scene, uid)
        return settings.rig if settings else None
    return rig_store.settings(context.scene).rig


def available(context, obj):
    return bool(obj and obj.mode in {'OBJECT', 'POSE'} and obj.name in context.view_layer.objects
                and not rig_store.deletion_busy(obj) and not pose_edit.busy())


def frame_range(scene, obj):
    """Use the active Action slot and the unmuted tracks that Blender evaluates."""
    animation = obj.animation_data
    ranges = []
    if animation:
        tracks = list(animation.nla_tracks) if animation.use_nla else []
        solo = any(track.is_solo for track in tracks)
        for track in tracks:
            if track.mute or (solo and not track.is_solo):
                continue
            ranges.extend((strip.frame_start, strip.frame_end) for strip in track.strips if not strip.mute)
        if animation.use_tweak_mode:
            action = animation.action_tweak_storage
            slot = rig.action_slot(action, animation.action_slot_handle_tweak_storage)
        else:
            action, slot = animation.action, animation.action_slot
        if action and (not action.is_action_layered or slot) and not solo and (not animation.use_nla or animation.action_influence != 0):
            ranges.extend(tuple(curve.range()) for curve in control_rig.action_curves(action, slot)
                          if not curve.mute and (curve.keyframe_points or curve.sampled_points))
    if not ranges:
        return scene.frame_current, scene.frame_current
    return math.floor(min(start for start, _ in ranges)), math.ceil(max(end for _, end in ranges))


@contextmanager
def clean_skeleton(context, obj):
    """Build an isolated SOMA-only object with the actor's exact rest bones."""
    scene = bpy.data.scenes.new('Motion AI · Bake')
    armature = None
    target = None
    try:
        scene.render.fps = context.scene.render.fps
        scene.render.fps_base = context.scene.render.fps_base
        scene.unit_settings.system = context.scene.unit_settings.system
        scene.unit_settings.scale_length = context.scene.unit_settings.scale_length
        armature = obj.data.copy()
        armature.animation_data_clear()
        armature.pose_position = 'POSE'
        target = bpy.data.objects.new(obj.name + ' · SOMA', armature)
        scene.collection.objects.link(target)
        layer = scene.view_layers[0]
        target.select_set(True, view_layer=layer)
        layer.objects.active = target
        with context.temp_override(scene=scene, view_layer=layer, active_object=target, object=target):
            bpy.ops.object.mode_set(mode='EDIT')
            try:
                for bone in list(armature.edit_bones):
                    if bone.name not in rig.NAMES:
                        armature.edit_bones.remove(bone)
            finally:
                bpy.ops.object.mode_set(mode='OBJECT')
            for collection in list(armature.collections_all):
                if collection.name.startswith('Controls ·'):
                    armature.collections.remove(collection)
            for name in ('SOMA Body', rig.FINGER_COLLECTION):
                collection = armature.collections.get(name)
                if collection:
                    collection.is_visible = True
            if rig.fingerprint(target) != rig.fingerprint(obj):
                raise ValueError('The baked skeleton differs from the SOMA rest pose.')
        yield scene, target
    finally:
        if target is not None:
            action = target.animation_data.action if target.animation_data else None
            bpy.data.objects.remove(target, do_unlink=True)
            if action and not action.users:
                bpy.data.actions.remove(action)
        if armature is not None and not armature.users:
            bpy.data.armatures.remove(armature)
        bpy.data.scenes.remove(scene)


class TransformKeys:
    def __init__(self):
        self.samples = [[array('f') for _ in range(count)] for count in (3, 4, 3)]
        self.rotation = None

    def append(self, frame, matrix):
        location, rotation, scale = matrix.decompose()
        if self.rotation is not None and self.rotation.dot(rotation) < 0:
            rotation.negate()
        self.rotation = rotation
        for channels, values in zip(self.samples, (location, rotation, scale)):
            for channel, value in zip(channels, values):
                channel.extend((frame, value))

    def write(self, bag, prefix=''):
        for prop, channels in zip(CHANNELS, self.samples):
            for axis, coordinates in enumerate(channels):
                nla_motion.add_linear_curve(bag, prefix + prop, axis, coordinates)


def sample_motion(context, obj, target, first, last):
    """Read the actual NLA/Action/constraint result with no layer overrides."""
    scene = context.scene
    current = scene.frame_current, scene.frame_subframe
    saved_pose = rig.pose_state(obj)
    object_channels = (*rig.TRANSFORM_CHANNELS, 'delta_location', 'delta_rotation_euler',
                       'delta_rotation_quaternion', 'delta_scale')
    saved_object = {name: tuple(getattr(obj, name)) for name in object_channels}
    bones = [target.data.bones[name] for name in rig.NAMES]
    keys = [TransformKeys() for _ in bones]
    # The FBX exporter reads the current frame for the static skeleton.
    # Frame zero supplies the rest transforms outside the exported clip.
    rest_basis = Matrix.Identity(4)
    for curves in keys:
        curves.append(0, rest_basis)
    with pose_preview.preserve_edit_state(context, exclude=(obj,)):
        try:
            for at in range(first, last + 1):
                scene.frame_set(at)
                evaluated = obj.evaluated_get(context.evaluated_depsgraph_get())
                if at == first:
                    export_origin = evaluated.matrix_world.copy()
                    inverse_origin = export_origin.inverted_safe()
                space = inverse_origin @ evaluated.matrix_world
                poses = [space @ evaluated.pose.bones[bone.name].matrix for bone in bones]
                frame = at - first + 1
                for bone, pose, parent, curves in zip(bones, poses, rig.PARENTS, keys):
                    parents = (dict(parent_matrix=poses[parent], parent_matrix_local=bones[parent].matrix_local)
                               if parent >= 0 else {})
                    basis = bone.convert_local_to_pose(pose, bone.matrix_local, invert=True, **parents)
                    curves.append(frame, basis)
        finally:
            scene.frame_set(current[0], subframe=current[1])
            rig.restore_pose_state(obj, saved_pose, only_changed=True)
            for name, value in saved_object.items():
                if tuple(getattr(obj, name)) != value:
                    setattr(obj, name, value)
    return keys, export_origin


def create_action(obj, target, keys):
    action = bpy.data.actions.new(obj.name + ' · Baked SOMA')
    try:
        slot = action.slots.new(id_type='OBJECT', name=obj.name)
        layer = action.layers.new('Baked SOMA')
        bag = layer.strips.new(type='KEYFRAME').channelbag(slot, ensure=True)
        for name, curves in zip(rig.NAMES, keys):
            prefix = target.pose.bones[name].path_from_id() + '.'
            curves.write(bag, prefix)
        return action, slot
    except BaseException:
        bpy.data.actions.remove(action)
        raise


def configure_soma(obj):
    for bone in obj.pose.bones:
        for constraint in list(bone.constraints):
            bone.constraints.remove(constraint)
        bone.rotation_mode = 'QUATERNION'
        bone.custom_shape = None
        bone.hide = bone.bone.hide = rig.auxiliary(bone.name)
        bone.bone.hide_select = False
        bone.select = False
    obj.data.bones.active = None
    obj.rotation_mode = 'QUATERNION'
    obj.delta_location = (0, 0, 0)
    obj.delta_rotation_euler = (0, 0, 0)
    obj.delta_rotation_quaternion = (1, 0, 0, 0)
    obj.delta_scale = (1, 1, 1)


def export_fbx(context, obj, filepath):
    if not filepath:
        raise ValueError('Choose a destination for the SOMA FBX.')
    filepath = Path(bpy.path.abspath(bpy.path.ensure_ext(filepath, '.fbx')))
    rig.validate_rig(obj)
    first, last = frame_range(context.scene, obj)
    with clean_skeleton(context, obj) as (scene, target):
        keys, basis = sample_motion(context, obj, target, first, last)
        action, slot = create_action(obj, target, keys)
        configure_soma(target)
        target.matrix_world = basis
        rig.assign_action(target, action, slot)
        scene.frame_start, scene.frame_end = 1, last - first + 1
        with TemporaryDirectory(dir=filepath.parent) as temporary:
            output = Path(temporary) / filepath.name
            with context.temp_override(scene=scene, view_layer=scene.view_layers[0], active_object=target, object=target):
                scene.frame_set(0)
                result = bpy.ops.export_scene.fbx(
                    filepath=str(output), check_existing=False, object_types={'ARMATURE'},
                    add_leaf_bones=False, use_armature_deform_only=False, bake_anim=True,
                    bake_anim_use_all_bones=True, bake_anim_use_nla_strips=False,
                    bake_anim_use_all_actions=False, bake_anim_force_startend_keying=True,
                    bake_anim_simplify_factor=0.,
                )
            if result != {'FINISHED'} or not output.is_file():
                raise ValueError('Blender could not write the SOMA FBX.')
            os.replace(output, filepath)
    return first, last


class TOYXYZ_OT_export_soma(bpy.types.Operator, ExportHelper):
    bl_idname = 'toyxyz_motion_ai_tool.export_soma'
    bl_label = 'Export FBX'
    bl_description = 'Export the selected actor’s visible motion on SOMA bones to one FBX'
    filename_ext = '.fbx'
    filter_glob: StringProperty(default='*.fbx', options={'HIDDEN'})
    actor_uid: StringProperty(options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return available(context, actor_for(context))

    def invoke(self, context, event):
        obj = actor_for(context)
        self.actor_uid = obj['toyxyz_uuid']
        self.filepath = bpy.path.abspath('//' + bpy.path.clean_name(obj.name) + self.filename_ext)
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        obj = actor_for(context, self.actor_uid)
        if not available(context, obj):
            self.report({'ERROR'}, 'The selected SOMA actor is unavailable.')
            return {'CANCELLED'}
        try:
            first, last = export_fbx(context, obj, self.filepath)
        except (OSError, ValueError, RuntimeError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        self.report({'INFO'}, f'Exported {last - first + 1} frames of SOMA motion.')
        return {'FINISHED'}


CLASSES = (TOYXYZ_OT_export_soma,)
