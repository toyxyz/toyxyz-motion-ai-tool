# Unified SOMA controls

**Withdrawn in 0.40.0 at the user's request.** Use [native SOMA bones](CONTROL_RIG_REMOVAL.md). The following is historical documentation; these controls are no longer shipped.

Version 0.39.3, 2026-11-09. This replaces the separate FK/IK mode workflow.

## Editing

All four limbs show their segment handles and a single hand/foot box together.
There is no limb-mode switch or hidden selection-based mode transition.

| Input | Result |
|---|---|
| Hand/foot box: G or the normal Move gizmo | Native Auto IK edits the parent joint rotations. |
| Upper/lower segment: R or Rotate gizmo | Ordinary FK rotation from the current pose; descendants follow. |
| Hand/foot box: R | Rotate the wrist/ankle. |
| Pole sphere: G or Move gizmo | Change bend direction while keeping the hand/foot transform. |
| I or Insert Pose Key | Key selected controls; an end/pole selection also keys its three-bone limb. |
| Auto Key | Native Auto IK keys affected parents; pole editing keys its canonical limb rotations. |

IK and FK can be alternated without snapping or switching a persistent mode.
The endpoint boxes are the existing CTRL_Hand/Foot bones; the old IK_ targets
remain hidden as legacy internal data. Only one endpoint control is visible.
Hips/master, toe/palm boxes, mesh deformation and pose-target display remain.
Keep Blender Pose Options > Auto IK enabled; it is saved on the actor by default.

Moving the hips or rotating a limb carries its descendants. There is no contact
pin or automatic footplant. Between keys, ordinary joint rotations interpolate;
this does not guarantee a straight hand path or a stationary foot.

## Canonical pose and native playback

The CTRL_ rotation channels hold the single authoritative limb pose. Connected
hand/foot controls have zero-influence targetless IK templates, chain length 3,
head targeting, no stretch, 128 iterations. Blender's native transform operation
uses them while translating and commits its result to the same rotation channels.
Boundary IK locks prevent a hand operation from changing an unkeyed shoulder or
body chain. Segment rotation remains normal Blender FK.

Original SOMA77 bone names, rest transforms, hierarchy and model payload are
unchanged. Generated animation stays in native NLA; the active user Action stays
a Combine correction layer. Existing generation code removes the same upper
correction from a regenerated lower result. New generated Actions no longer
need duplicate IK-target or pole-location trajectories. Empty user channels are
reserved for native Auto Key over NLA. They contain no keys and are excluded
from authored constraints/correction evaluation.

The armature retains four hidden reference helpers (179 bones total), but the
visible Pole bones are now real, unparented, unconstrained inputs. There is no
Copy Location display override on them. Their native position is the displayed
sphere position and the Move gizmo input position.

Pole editing uses Blender's **builtin Move** gizmo and native **G**. No Move Pole
toolbar entry, replacement gizmo group or G keymap is registered. During a gesture
Python reads the actual free bone position and rotates the original limb around
the root-to-end axis from one start snapshot. The hand/foot matrix, joint bend
angle and segment lengths are retained. The real handle follows the requested
3D displacement, including radial/axial movement, and stays there on confirmation.

Outside a gesture, Python carries the free pole with the upper-limb frame using
a stored local display anchor. No canonical pose is derived from these display
updates. The guard/cache distinguishes FK/IK edits, native pole input, frame
sampling and Undo. Near-axis starts use a finite virtual angular radius so a
small move is not converted into an abrupt large bend-plane rotation. A zero
input/cancel restores the original pose and key data.

I and Auto Key store canonical limb rotations plus the local anchor metadata.
Anchor keys are not additional model constraints or pose times, but they move
and delete with a user pose in the addon timeline. Temporary native location
keys are cleared only on managed working Actions; legacy/backup authored curves
are retained. Model regeneration continues to subtract the same user correction
from the new lower NLA motion, independently of this display metadata.

Synchronization runs on Blender's main thread. For this two-joint operation a
separate Python process would still require main-thread application and stale
response handling, while adding IPC. The actual mismatch was the constrained
input/display split, so this update uses independent addon Python rather than
launching another worker. It does not change the companion/model process design
or modify any paused external-solver experiment.

Saved motion still plays natively. Pole interaction/following requires the addon;
native hand/foot Auto IK and FK editing work with it disabled. A workspace saved
with the removed old tool is returned to builtin Move once.

## Existing scenes

Controlled actors convert once while idle after restarting Blender. Edit Mode,
shared armature data, NLA Tweak Mode and an active generation defer conversion.
The active user Action is copied and its original retained with a fake user.
Composed limb rotations are converted at existing authored pose times, and old
user IK/pole/mode channels are removed from the working copy. Current pose,
block IDs and actor identity remain. Generated base Actions are retained.

Sparse key interpolation can change because endpoint curves are now represented
by joint rotation curves. Existing keyed poses are preserved within measured
native IK tolerances; this is not an exact conversion of every intermediate
frame or a retained world-space contact trajectory. Source .blend files are
not overwritten automatically. Save normally after reviewing the conversion.

## Validation

Actual Blender 5.2.3 LTS background checks cover:

- Four limbs, repeated native FK -> IK -> FK edits, normal and centimeter units.
- Native world displacement with translated/rotated/uniformly scaled actors.
- Pole end-pose retention, 30 identical absolute previews, cancellation, native
  Undo/Redo and canonical Auto Key with a second actor left unchanged.
- Native NLA plus Auto Key/manual I, frame replay, regeneration without double
  correction, pose-preview state preservation, Clear Motion and rest hashing.
- Original Action/source-file preservation, old pose-time preservation and
  save/reopen; later native hand IK editing with the addon disabled.
- Recorded Kimodo, MotionBricks and ARDY outputs versus canonical playback.
  The old 60-frame MotionBricks fixture is cropped to today's 58-frame single
  block limit at 30 FPS. No new model inference is needed for this replay check.

Source measurements: maximum native IK target error 0.023 mm; native Auto Key
replay matrix-component difference 1.60e-5 in normal units. The legacy centimeter
fixture has maximum keyed position difference 0.316 mm and rotation-matrix entry
difference 6.86e-4. Recorded model playback position differences are below
0.002 mm. These fixtures do not establish arbitrary-pose or interactive usability
quality. Nonuniform object scale/shear and persistent hand/foot pinning are not
part of this update.

Evidence is in results/unified_controls: installed.json,
installed_centimeters.json, migration_installed.json, models_installed.json and
undo_installed.json. Tests are build_tools/test_unified_controls*.py.

Actual mouse dragging, gizmo hit testing and modal Escape/right-click behavior
still require manual user review; the background checks exercise native execute
paths and the explicit gesture core. No computer-use automation was used.

Manual review scene: results/unified_controls/unified_controls_review.blend.
Both actors use unified controls. The blue actor is neutral; the orange actor
has a hand IK edit. READ_ME_CONTROL_RIG inside the scene explains operation.
The adjacent PNG renders disposable widget geometry; it is absent from the
saved scene. See the older CONTROL_RIG.md for historical FK/IK implementation.

## Pole continuity repair (0.39.1)

Version 0.39.0 derived a pole by normalizing the elbow/knee perpendicular to the
root-to-end line. FK crossing a straight joint reverses that vector; a fixed
0.4 m offset then jumps about 0.8 m. Reproduction evidence is
results/unified_controls/pole_flip_before.json and legacy_pole_flip.blend.

The repair replaces these geometric drivers with the native upper-limb frame
attachment above. Existing unified actors repair once while idle. Only hidden
helper rest/parent data, their obsolete drivers and cached helper defaults for
Clear Motion change. Original bone pose, source Action, user key values/times,
generated NLA and the original SOMA rest contract remain. The source .blend is
not overwritten. No runtime pose writeback or temporal smoothing is introduced.

The focused regression runs 10,608 samples over all four limbs and all three
rotation axes, including straight/folded transitions and wrist/ankle rotation.
The maximum adjacent display motion was 10.46 mm for a one-degree upper-segment
rotation; lower-segment/end rotations retain the attachment within 0.002 mm.
Tests also cover zero-input pole previews after positive/negative FK bends,
no endpoint drift, no angular confirmation snap, old keyed/NLA repair without
Action changes, Clear Motion and native save/reopen. Evidence:
results/unified_controls/pole_continuity_installed.json and
pole_continuity_installed_centimeters.json; test: build_tools/test_pole_continuity.py.
These are background/numerical checks, not mouse-interaction approval.

## Hand display and native Move update (0.39.2)

Hand boxes now use the neutral actor axes rather than the wrist-to-knuckle frame.
Their edges are parallel in front and top orthographic views, with an 8 mm margin
around the combined palm, thumb and finger skin region and joint landmarks.
Display offsets/rotation compensate for the wrist's unchanged pivot/rest axes.
Both hands update once on existing actors; native keys and mesh deformation are
unchanged. Review renders: results/unified_controls/hand_box_front.png and
hand_box_top.png. The bone widget shape remains a native Blender custom shape.

The old Move Pole workspace tool and custom gizmo group are removed. The current
native-input route is described above and covered by
build_tools/test_native_move_and_hand_boxes.py. Its installed report is
results/unified_controls/native_move_installed.json. Checks include both neutral
box projections, fingertip enclosure, all four native Move pole paths, cancellation
at existing NLA keys including handle metadata, transformed actor coordinates,
rapid subsequent FK edits and unmanaged backup-Action preservation. Measured box
axis-component error is 2.24e-7; the tested native pole Auto Key replay error is 0.

This Blender build crashes in ED_area_type_hud_ensure for an explicit headless
native transform call with undo=True, also in factory startup without this addon
(results/headless_undo.log). Background Undo/Redo checks therefore use explicit
Undo snapshots. Actual mouse dragging, native modal Escape/right-click and UI
Undo grouping remain for the user to verify, without computer-use automation.

## Free Pole synchronization repair (0.39.3)

The constrained 0.39.2 display followed a circular bend-plane result while native
Move used a different free translation input. A synthetic bent-limb reproduction
measured 92-141 mm between the requested and displayed position. Evidence:
results/unified_controls/pole_translation_before.json and the preserved
legacy_pole_cursor_mismatch.blend. Arithmetic synchronization alone could not
make a fully constrained display behave like the actual native input.

The new free controls remove that override. Existing actors upgrade in place,
keeping their current visible pole positions, canonical pose and active user
Action. Layout anchors are captured from the displayed pose, then future FK/IK
moves and gesture results update one real control. Original scene files are not
overwritten. New anchor metadata is included in edit-state preservation and
native key/timeline handling, without entering the 77-joint model payload.

The focused native-transform regression covers all four limbs with ten continuous
translation steps each, no confirmation snap, fixed endpoints, FK following,
near-axis recovery, anchor-key playback, no extra model target times, live-preview
preservation, timeline key movement, pre-fix upgrade and native save/reopen.
Normal-unit maximum live position error was 6.1e-8 m; centimeter scene error was
6.8e-8 m. These are background execute-path measurements, not mouse UX approval.

Evidence: results/unified_controls/free_pole_installed.json and
free_pole_installed_centimeters.json; test: build_tools/test_free_pole_alignment.py.
The general native-Move/NLA/cancel/Undo/model replay checks are rerun as well.

Manual review scene: results/unified_controls/free_pole_interaction_review.blend.
It contains a bent left leg, selects Pole_LeftLeg, and uses Blender's builtin Move.
Actual gizmo hit testing, mouse dragging and modal cancel/Undo grouping remain
for manual user review. The headless Undo=True HUD limitation described above
still applies; background Undo checks use explicit snapshots.
