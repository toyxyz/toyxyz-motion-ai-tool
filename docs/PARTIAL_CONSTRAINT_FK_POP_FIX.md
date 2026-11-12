# Partial constraint FK pop correction (v0.22.1)

Hand constraints in the supplied `motion_error.blend` produced a one-frame arm pop when the generated result was applied to Blender. The cause was in addon NLA baking, not a discontinuity of the same size in the model output.

`unified.capture()` records composed local transform channels at native user keys. Previously, `nla_motion.bake_action()` passed all of these records to `unified.components()`, which restored their exact values at those frames before subtracting the user correction. This is intentional for Full Body targets. A hand target constrains the hand position/orientation, however, and permits different shoulder/elbow rotations. Restoring the old FK channels at only that frame introduces a spike and can also disturb the generated hand target.

`unified.full_body_overrides()` now limits this exact local-channel restoration to FB frames. LH/RH/LF/RF/R2 retain the generated solution, with the existing source correction counterbalanced in the base as usual. The original user Action, slot, key values/times, handles and interpolation remain unchanged. User edits after generation still combine through native NLA. The existing root-curve policy remains in place.

## Supplied-scene replay

The scene uses 60 FPS, a single SOMA armature and one generated clip spanning [1,121). It has RH at frame 23 and LH at frame 61. The replay uses the **same cached raw result** from job `8943424e8c2c4f67a136efafd3670e15`; there is no new inference or seed change.

| Key | Bone | Previous-frame local rotation change before | After |
|---|---|---:|---:|
| RH 23 | RightArm | 34.2309 degrees | 3.8259 degrees |
| RH 23 | RightForeArm | 11.6246 degrees | 1.1205 degrees |
| LH 61 | LeftArm | 23.6781 degrees | 0.6772 degrees |
| LH 61 | LeftForeArm | 24.7842 degrees | 0.7011 degrees |

The corrected scene still has one SOMA armature and one playback track. Source Action/slot and key coordinates, handles and interpolation compare exactly before and after. These measurements diagnose this scene's application-stage spike; they do not establish general motion quality or exact endpoint pinning for arbitrary poses.

Evidence under `results/blender_bridge/hand_constraint_diagnosis/`:

- `motion_error_original.blend`: byte-identical workspace copy of the supplied scene.
- `supplied_scene_before.json`: original scene/model comparison.
- `isolated_candidate_replay.json`: initial isolated candidate replay.
- `fixed_scene_replay.json`: actual v0.22.1 production-code replay and preservation assertions.
- `installed_reopen.json`: installed/source file equality, version, original SHA-256, preserved source keys after reopening, and identical native playback with the addon disabled.
- `motion_error_repaired.blend`: repaired copy with native NLA playback.

`build_tools/replay_hand_constraint_fix.py` reproduces the production-code replay in a separate background Blender process. The existing `build_tools/test_layered_corrections.py` regression passes: Full Body keyed final rotations, preserved correction values/times, Auto Key, native key deletion/Undo/Redo, inherited endpoints, save/reopen and addon-disabled native playback.

Existing saved clips are not rewritten automatically by installing the addon. Regenerate affected blocks after restarting Blender, or inspect the repaired copy. The original supplied file was not overwritten. The companion app does not require a restart for this addon-only fix.
