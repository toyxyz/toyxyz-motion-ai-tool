"""Verify a non-destructive one-actor SOMA FBX round trip."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import addon_utils
import bpy
from mathutils import Matrix, Quaternion

ROOT = Path(__file__).resolve().parents[1]
if '--installed' not in sys.argv:
    sys.path.insert(0, str(ROOT / 'addons'))
addon_utils.enable('toyxyz_motion_ai_tool', default_set=False)
import toyxyz_motion_ai_tool as addon
from toyxyz_motion_ai_tool import control_layers, control_rig, final_motion, rig, timeline

assert 'bake_soma' not in dir(bpy.ops.toyxyz_motion_ai_tool)


def heads(context, actor):
    evaluated = actor.evaluated_get(context.evaluated_depsgraph_get())
    return {bone.name: evaluated.matrix_world @ bone.head for bone in evaluated.pose.bones if bone.name in rig.NAMES}


def compare(expected, actual, tolerance):
    assert set(actual) == set(expected) == set(rig.NAMES)
    error = max((expected[name] - actual[name]).length for name in rig.NAMES)
    assert error < tolerance, error
    return error


def rest_matrices(actor):
    return {name: actor.data.bones[name].matrix_local.copy() for name in rig.NAMES}


def matrix_error(expected, actual):
    return max(abs(a - b) for name in rig.NAMES for row_a, row_b in zip(expected[name], actual[name])
               for a, b in zip(row_a, row_b))


def key(context, obj, name, frame, prop, value):
    context.scene.frame_set(frame)
    bone = obj.pose.bones[name]
    setattr(bone, prop, value)
    assert bone.keyframe_insert(prop, frame=frame)


def signature(context, settings, actor):
    ad = actor.animation_data
    return (actor.data, ad.action, ad.action_slot, ad.use_tweak_mode, ad.use_nla, ad.action_blend_type,
            tuple((track, track.mute, track.is_solo, tuple((strip, strip.action, strip.action_slot,
                  strip.mute, strip.frame_start, strip.frame_end) for strip in track.strips)) for track in ad.nla_tracks),
            tuple((block.uid, block.start, block.end, block.has_result, block.selected) for block in settings.blocks),
            settings.selection, context.scene.frame_current, context.scene.frame_subframe,
            context.view_layer.objects.active, tuple(context.selected_objects), actor.mode,
            len(bpy.data.scenes), len(bpy.data.objects), len(bpy.data.armatures), len(bpy.data.actions))


context = bpy.context
scene = context.scene
scene.render.fps = 30
assert bpy.ops.toyxyz_motion_ai_tool.add_soma() == {'FINISHED'}
other = addon.settings(context).rig
other.location.x = 12
assert bpy.ops.toyxyz_motion_ai_tool.setup_controls() == {'FINISHED'}
other_data = other.data
assert bpy.ops.toyxyz_motion_ai_tool.add_soma() == {'FINISHED'}
settings = addon.settings(context)
actor = settings.rig
actor.location = (2, -.5, .3)
assert bpy.ops.toyxyz_motion_ai_tool.setup_controls() == {'FINISHED'}
rest = rig.fingerprint(actor)
neutral = rest_matrices(actor)
skin = tuple(actor.children)
block = settings.blocks[0]
block.engine = 'ardy'
timeline.set_range(block, 5, 25)
base = rig.snapshot(context, actor)
samples = []
for index in range(20):
    pose = [list(map(list, Matrix.Identity(3))) for _ in rig.NAMES]
    pose[rig.NAMES.index('LeftArm')] = list(map(list, Matrix.Rotation(.2 + .01 * index, 3, 'Z')))
    samples.append(pose)
rig.import_result(context, actor, dict(
    status='succeeded', engine='ardy', job_id='final_motion_fixture', joint_names=rig.NAMES,
    start=5, end=25, fps=30, scene_fps=30, local_rotations=samples,
    root_positions=[(base['root'][0] + index * .04, *base['root'][1:]) for index in range(20)],
    blocks=[dict(start=5, end=25, engine='ardy', uid=block.uid, name=block.name, prompt=block.prompt)],
))
context.scene.frame_set(9)
control_rig.switch(context, actor, 'LeftArm', 1.)
context.scene.frame_set(17)
control_rig.switch(context, actor, 'LeftArm', 0.)
key(context, actor, control_rig.fk('RightArm'), 12, 'rotation_quaternion', Quaternion((0, 1, 0), .2))
actor.location = (2, -.5, .3)
actor.keyframe_insert('location', frame=5)
actor.location = (2.45, -.5, .3)
actor.keyframe_insert('location', frame=25)
muted = control_layers.add(context, settings, 2, 31)
key(context, actor, control_rig.fk('RightHandIndex1'), 12, 'rotation_quaternion', Quaternion((1, 0, 0), .7))
control_layers.deselect(context, settings)
control_layers.toggle(context, settings, muted)
active = control_layers.add(context, settings, 4, 26)
key(context, actor, control_rig.fk('Head'), 4, 'rotation_quaternion', Quaternion((1, 0, 0), .5))
key(context, actor, control_rig.fk('LeftHandIndex1'), 12, 'rotation_quaternion', Quaternion((0, 1, 0), .65))
assert control_layers.editing(actor) == active
assert final_motion.frame_range(scene, actor) == (4, 26)
poses = {}
for frame in range(4, 27):
    scene.frame_set(frame)
    poses[frame] = heads(context, actor)
assert (poses[23]['Hips'] - poses[6]['Hips']).length > .3
scene.frame_set(4)
first_pose = {name: actor.pose.bones[name].matrix.copy() for name in rig.NAMES}
assert matrix_error(neutral, first_pose) > .1
scene.frame_set(12, subframe=.25)
before = signature(context, settings, actor)
visible = heads(context, actor)

with TemporaryDirectory() as directory:
    path = Path(directory) / 'actor.fbx'
    assert bpy.ops.toyxyz_motion_ai_tool.export_soma(filepath=str(path)) == {'FINISHED'}
    assert path.is_file() and list(Path(directory).iterdir()) == [path]
    assert signature(context, settings, actor) == before
    assert other.data == other_data and control_rig.enabled(other)
    assert tuple(actor.children) == skin and rig.fingerprint(actor) == rest and control_rig.enabled(actor)
    compare(visible, heads(context, actor), 1e-5)
    for importer in (bpy.ops.wm.fbx_import, bpy.ops.import_scene.fbx):
        imported_scene = bpy.data.scenes.new('FBX Review')
        with context.temp_override(scene=imported_scene, view_layer=imported_scene.view_layers[0]):
            assert importer(filepath=str(path), anim_offset=0.) == {'FINISHED'}
            imported = list(imported_scene.objects)
            assert len(imported) == 1 and imported[0].type == 'ARMATURE'
            skeleton = imported[0]
            assert set(skeleton.data.bones.keys()) == set(rig.NAMES)
            neutral_error = matrix_error(neutral, rest_matrices(skeleton))
            assert neutral_error < 1e-4, neutral_error
            frame_range = tuple(skeleton.animation_data.action.frame_range)
            assert frame_range == (1., 23.), frame_range
            import_error = 0.
            for frame, expected in poses.items():
                imported_scene.frame_set(frame - 3)
                import_error = max(import_error, compare(expected, heads(context, skeleton), 1e-4))
            imported_scene.frame_set(1)
            first_import = {name: skeleton.pose.bones[name].matrix.copy() for name in rig.NAMES}
            assert matrix_error(first_pose, first_import) < 1e-4
        print(importer.idname(), 'maximum rest matrix and animated joint head errors:', neutral_error,
              import_error, flush=True)

