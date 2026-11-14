"""Run in background Blender to verify short native joins between motion blocks."""
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

import addon_utils
import bpy
from mathutils import Matrix

sys.path.insert(0,str(Path(__file__).resolve().parents[1] / 'addons'))
assert addon_utils.enable('toyxyz_motion_ai_tool')
from toyxyz_motion_ai_tool import continuity, control_rig, correction_bounds, keyframes, rig, rig_store, seam_blend, timeline


def transitions(obj):
    return next((t for t in obj.animation_data.nla_tracks if t.name == seam_blend.LABEL), None)


def run(fps, engines, control=False, correction=False):
    context = bpy.context
    scene = context.scene
    scene.render.fps = fps
    assert bpy.ops.toyxyz_motion_ai_tool.add_soma() == {'FINISHED'}
    settings = rig_store.settings(scene)
    obj = settings.rig
    if control:
        assert bpy.ops.toyxyz_motion_ai_tool.setup_controls() == {'FINISHED'}
    rotations = rig.model_snapshot(context,obj)['local_rotations']
    first = settings.blocks[0]
    first.engine = engines[0]
    cut = 1 + 2*fps
    timeline.set_range(first,1,cut)
    second = timeline.add(scene)
    second.engine = engines[1]
    # MotionBricks accepts at most 58 model frames per block.
    timeline.set_range(second,cut,cut+fps)

    def apply(block, offset, step, job):
        count = round((block.end-block.start)*30/fps)
        local = []
        roots = []
        for i in range(count):
            x = offset+i*step
            values = list(rotations)
            values[rig.NAMES.index('LeftArm')] = list(map(list,Matrix.Rotation(x*.4,3,'X')))
            local.append(values)
            roots.append([x,1.0,0.0])
        rig.import_result(context,obj,dict(
            status='succeeded',engine=block.engine,start=block.start,end=block.end,
            fps=30,scene_fps=fps,job_id=job,joint_names=rig.NAMES,
            local_rotations=local,root_positions=roots,
            blocks=[dict(start=block.start,end=block.end,uid=block.uid,name=block.name)]))

    def pose(frame):
        scene.frame_set(frame)
        context.view_layer.update()
        return rig.model_snapshot(context,obj)

    apply(first,0.0,.032,f'previous-{fps}')
    original = pose(cut-10)
    assert not transitions(obj)
    if correction:
        from mathutils import Quaternion, Vector

        # Author a correction for the next block before generating it. The
        # guard cancels its backward extrapolation at the shared boundary.
        frame = cut + fps//2
        pose(frame)
        hips = obj.pose.bones['Hips']
        arm = obj.pose.bones['LeftArm']
        hips.location += Vector((.22,.16,0))
        arm.rotation_quaternion @= Quaternion((0,1,0),.3)
        assert hips.keyframe_insert('location',frame=frame)
        assert arm.keyframe_insert('rotation_quaternion',frame=frame)
        correction_bounds.sync(scene,obj)
        assert correction_bounds.track(obj)
    apply(second,59*.032,.020,f'following-{fps}')
    layer = transitions(obj)
    assert layer and len(layer.strips)==1 and layer.lock
    strip = layer.strips[0]
    assert int(strip.frame_start)==cut-round(fps*.1)
    assert int(strip.frame_end)==cut+round(fps*.10)
    playback = continuity.playback(obj)
    assert list(obj.animation_data.nla_tracks).index(layer)>list(obj.animation_data.nla_tracks).index(playback)
    assert math.dist(original['root'],pose(cut-10)['root'])<1e-6
    positions = [pose(f)['root'][0] for f in range(cut-3,cut+4)]
    assert min(b-a for a,b in zip(positions,positions[1:]))>.004, positions
    if correction:
        roots = [pose(f)['root'] for f in range(cut-3,cut+4)]
        steps = [math.dist(a,b) for a,b in zip(roots,roots[1:])]
        assert max(steps)<.03, steps
        arm_samples = [Matrix(pose(f)['local_rotations'][rig.NAMES.index('LeftArm')]).to_quaternion()
                       for f in range(cut-3,cut+4)]
        assert max(a.rotation_difference(b).angle for a,b in zip(arm_samples,arm_samples[1:]))<.05

    # A file saved with the previous contact-lock transition must rebuild it
    # from the two original generated clips.
    old_action = strip.action.name
    legacy_tag = strip.action[seam_blend.TAG].replace(f'[{seam_blend.REVISION},', '[2,', 1)
    strip.action[seam_blend.TAG] = legacy_tag
    obj[seam_blend.TRACK_STATE] = json.dumps([legacy_tag])
    seam_blend.sync(scene,obj,playback)
    layer = transitions(obj)
    assert layer and layer.strips[0].action.name != old_action
    assert bpy.data.actions.get(old_action) is None

    # A gap removes the overlay and leaves the outgoing NLA hold in effect.
    timeline.set_range(second,cut+2,cut+2+fps)
    correction_bounds.sync(scene,obj)
    assert not transitions(obj)
    assert math.dist(pose(cut)['root'],pose(cut+1)['root'])<1e-6
    timeline.set_range(second,cut,cut+fps)
    correction_bounds.sync(scene,obj)
    seam_blend.sync(scene,obj,continuity.playback(obj),force=True)
    assert transitions(obj)

    # Reopening preserves native animation without evaluating any Python player.
    if fps==60:
        name = obj.name
        before = pose(cut)
        with TemporaryDirectory() as directory:
            filepath = str(Path(directory)/'seams.blend')
            bpy.ops.wm.save_as_mainfile(filepath=filepath,copy=True)
            bpy.ops.wm.open_mainfile(filepath=filepath,use_scripts=False)
        scene = context.scene
        obj = scene.objects[name]
        assert transitions(obj)
        assert math.dist(before['root'],pose(cut)['root'])<1e-6

    # Late explicit pose keys also take precedence over automatic joining.
    name = control_rig.fk('LeftArm') if control else 'LeftArm'
    bone = obj.pose.bones[name]
    if fps==60:
        scene.frame_set(cut-3)
        assert bone.keyframe_insert('rotation_quaternion',frame=cut-3)
        authored=[tuple(point.co) for curve in keyframes.curves(obj)
                  for point in curve.keyframe_points]
        seam_blend.sync(scene,obj,continuity.playback(obj),force=True)
        assert transitions(obj).strips[0].frame_start==cut-3
        assert authored==[tuple(point.co) for curve in keyframes.curves(obj)
                          for point in curve.keyframe_points]
    scene.frame_set(cut)
    assert bone.keyframe_insert('rotation_quaternion',frame=cut)
    track = continuity.playback(obj)
    seam_blend.sync(scene,obj,track,force=True)
    assert not transitions(obj)
    print('BLOCK SEAM PASS', fps, engines, control, flush=True)


run(30,('ardy','motionbricks'))
run(60,('kimodo','kimodo'),control=True)
run(60,('ardy','ardy'),correction=True)
