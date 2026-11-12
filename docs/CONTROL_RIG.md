# SOMA FK/IK control rig

For the current release, see [SOMA FK and IK controls](SPLIT_CONTROL_RIG.md).

**Withdrawn in 0.40.0 at the user's request.** Use [native SOMA bones](CONTROL_RIG_REMOVAL.md). The following is historical documentation; these controls are no longer shipped.

**Current workflow: [Unified controls, version 0.39.0](UNIFIED_CONTROLS.md).** The mode-switch and Pole Parent instructions below document versions 0.37-0.38 and are superseded for converted actors.

Version 0.37.0, 2026-11-08. Native controls for the existing SOMA actor, using the
layout reviewed in [the supplied reference](CONTROL_RIG_REFERENCE.md).

Display update 0.37.1: FK hands now use boxes like the IK hand targets. End/Eye
controller widgets are removed and their internal bones are hidden in both the
bone and pose display. Existing controlled actors receive this display update
once on refresh after restarting Blender. Keys, constraints and the original
SOMA endpoints remain intact.

Display update 0.37.2 also removes the Jaw widget. The head handle is a centered
box fitted to the neutral SOMA skin's head/face region, with a 1.5 cm margin.
Its display translation and orientation compensate for the Head bone's pivot
and rest axes, without changing the bone or its animation. Existing actors
receive this display update once on refresh.

Display update 0.37.3 fits both FK and IK hand boxes to the palm-weighted neutral
skin region, with an 8 mm margin. Wrist-to-middle-knuckle and index-to-pinky
directions define the box axes. Both modes therefore use the same palm-centered
box instead of the Hand bone's thumb-facing local axes. Display offsets only
are changed; pivot, constraints and keys retain their original transforms.

Version 0.37.4 fixes fingers/toes remaining at their FK positions during IK
editing. Descendants of the four hand/foot outputs now copy their controller's
local transform, inheriting their solved wrist/ankle parent. Limb outputs keep
their existing pose-space solutions. Existing controlled actors are repaired
once on refresh without changing keys, rest transforms or block data.
Installed regression checks move and rotate all four IK targets over generated
NLA and verify every descendant retains its local articulation while following
the end effector. The normal-unit maximum measured relative matrix/position
component error is 4.93e-7. Evidence is the `finger_toe_follow_error` measurement
in `results/control_rig/installed.json`.

Display update 0.37.5 replaces FK/IK foot handles and toe-base handles with
centered boxes. Separate neutral skin regions fit the main foot and toes, with
an 8 mm margin. Box axes follow the foot/toe direction and sole plane. Existing
actors update once on refresh; all keyed channels, pivots and IK constraints
remain unchanged. Toe End stays hidden as an endpoint marker.

## Control parenting update (0.38.0)

The 0.37.4 fix made the output fingers/toes inherit solved IK transforms, but
the visible finger/toe FK controllers still had FK-only parents. Their boxes
could therefore remain behind while the correctly deformed foot moved. Root
finger and toe controllers now parent to their solved original Hand/Foot output
bones, retaining identical rest transforms and local animation channels. The
visible control, native gizmo and output bone share the solved location.

Each limb now has **Pole Parent** buttons:

- **IK Control** (initial setting): the pole follows the hand/foot target's
  translation and rotation.
- **Master**: the pole follows the actor master independently of hand/foot
  movement.

Parent switching keeps the current pole position and inserts a stepped parent
key plus a pole-location key. The implementation uses native Child Of constraints
and inverse transforms, rather than frame handlers. Child Of uses a pose-space
owner and world-space target so actor object transforms do not enter twice.
Master transforms are applied once. These general principles were checked against the installed Auto-Rig Pro
`src/auto_rig.py` pole-parent setup and `src/rig_functions.py::_snap_pole`;
their hashes still match the reference bundle. No ARP code is imported or copied.
The additional ARP Smart space is not part of this update.

Existing actors upgrade once while idle after restarting Blender. Their original
user and generated Actions are retained as backups, and private copies convert
pole coordinates to the new parent space. Original pose-frame times, rest
skeleton and blocks remain. Added converted pole channels use those same pose
times. Keyed poses are retained; parent-space changes can alter interpolation
between sparse user keys. Shared armature data must be made single-user before
this structural upgrade. Source `.blend` files are never overwritten automatically.

`test_control_spaces.py` checks all four targets, toe-controller/output agreement,
parent switching, master motion without double transforms, regeneration with
animated parent selection, old-key/NLA migration and save/reopen. The normal-unit
test's pole follow matrix error is 4.77e-7, including a translated, rotated and
uniformly scaled actor object; the keyed legacy fixture's maximum
matrix-component migration difference is 6.11e-5 (the latter file uses centimeter
scene units). These are numerical fixture checks, not interactive usability
approval. Evidence: `results/control_rig/spaces_installed.json`.

## Usage

Restart Blender after updating the addon. The companion does not need an update
for controller pose inputs: its 77-joint request format is unchanged.

- **Add** creates an actor with controls and its skinned body together.
- For an existing actor, select it and click **Add Control Rig** once. Existing
  native user keys and NLA Actions are copied to controller channel paths;
  original Actions remain as backups. The actor, blocks and persistent IDs remain.
- Use **Control Rig** in the Motion AI sidebar to switch each arm/leg between
  **FK** and **IK**. Switching snaps to the displayed pose and inserts native
  controller keys at the current frame, plus a stepped mode transition. Switching
  to the already active mode does not add keys.
- FK: rotate the segment handles. IK: move/rotate the hand or foot boxes and move
  the small sphere poles to set elbow/knee direction. Active-mode handles are
  shown; inactive limb handles have zero display scale.
- The pelvis ring is **CTRL_Hips**. The large ground circle is **CTRL_Master**.
  Master translation/rotation moves the entire posed actor, including IK targets.
  Moving the hips changes the body independently of the master-parented targets.
- Insert ordinary transform keys on the controllers with Blender's normal keying
  tools. Those keys appear in the dedicated timeline and supply the evaluated
  Full Body/hand/foot/root constraints through the existing constraint-type UI.
  Mode-only transition keys are not separate pose targets. Moving/deleting a pose
  in the dedicated timeline also moves/deletes its associated mode key.

New actors default to FK. Body/head/shoulder controls remain FK. Finger controls
are in **Controls · Fingers**, hidden by default; End/Eye controls remain hidden.
There is no stretch, foot-roll system, automated contact, balance or finger IK.
The IK system uses the existing fixed SOMA segment lengths.

The standalone review file is
`results/control_rig/soma_control_rig_review.blend`: blue `actor_01` is FK and
orange `actor_02` is IK. `READ_ME_CONTROL_RIG` inside the file describes editing.
The adjacent PNG is an offscreen geometry rendering of the native bone shapes;
the temporary render geometry is not in the saved review scene.

## Native structure and model integration

Each actor still has one armature. It contains:

- The original 77 SOMA bones, with unchanged names, parents, rest matrices and
  lengths. These remain the model interface and deform the existing preview.
- 77 FK controller bones with matching rest transforms, eight IK target/pole
  bones, one master and twelve hidden IK mechanism bones: 175 bones total.
- Native constraints and simple property drivers; no frame callback performs
  pose solving. The shared primitive widget geometry is independently generated,
  without copying the reference rig's code or widget assets.

The hidden two-bone IK chains are independent of animated FK rotations, avoiding
pole reversal from applying IK directly to changing FK input. Their bend seed
avoids a perfectly straight-chain singularity. SOMA outputs retain the FK
orientation's axial twist and use native direction constraints toward the IK
joint positions. End orientation comes from the hand/foot target. Native Pole
angles are calibrated during setup against a temporary bent FK pose, then all
temporary channels are restored.

Generated Actions contain both FK transforms and matching IK target/pole paths.
Thus changing IK mode does not freeze the end effector at its last edited frame
while generated motion plays. The existing native Combine user-correction layer
remains active. Regeneration subtracts the same controller corrections from the
new lower layer. Animated master transforms are removed from the generated
controller base before composition, so their placement is not applied twice.
Path Curve placement takes precedence over old full-body location overrides.

The model receives only the final evaluated original 77-joint SOMA pose, not
controllers, IK parameters or a changed skeleton. Kimodo, ARDY and MotionBricks
use the existing constraint payloads. Pose preview preserves live controller
transforms and IK properties across temporary frame sampling.

Legacy setup copies only this actor's active and NLA Actions before remapping
SOMA channel paths; it does not rewrite shared originals or another actor's
animation. Existing generated clips gain matching IK trajectories. Setup does
not rewrite the source `.blend`; save normally to persist the upgrade. Setup
requires single-user armature data, no custom constraints on original SOMA
bones, and no active NLA Tweak Mode or generation for that actor. The existing
SOMA rest validation still applies.

## Verification and limits

Actual Blender 5.2.3 background tests pass against the installed addon, in both
normal and centimeter scene units:

- All four posed limbs snap FK -> IK -> FK. Maximum measured local rotation/root
  component difference is 7.68e-5; this combines matrix components and root
  coordinates and is not an angular accuracy measurement.
- Lowering hips by 1 cm while both feet use IK retains their positions within
  0.013 mm in the tested reachable pose.
- Controller keys supply the same composed pose to model requests. Synthetic
  regeneration, including animated master placement, retains keys and does not
  double corrections. Pose-target preview preserves live editing state.
- Existing native keys/NLA migrate with maximum component difference 9.54e-7.
  Original Action channels, source file hash, actor UUID, skeleton rest hash and
  block IDs are retained. Pose-key movement/deletion carries mode keys. Clear
  Motion, native switch Undo/Redo, save/reopen and addon-disabled playback pass.

Recorded real model results were also replayed in FK and IK without running new
inference. The sampled joint-position differences were:

| Model fixture | Samples | Maximum FK/IK joint-position difference |
|---|---:|---:|
| Kimodo | 30 | 1.23 mm |
| MotionBricks | 30 | 0.67 mm |
| ARDY | 22 | 0.94 mm |

Their maximum local rotation-matrix entry differences were 0.00572, 0.00482 and
0.00438 respectively. Native IK tolerances and nearly straight chains mean IK
playback is not mathematically identical to FK. These fixtures establish native
integration, not arbitrary-pose solvability, character retargeting quality or
interactive usability approval. Unreachable targets stop at fixed limb reach.
Interactive gizmo selection, handle sizing and subjective control feel remain
for user review; no computer-use automation was used.

Evidence: `results/control_rig/installed.json`, `installed_centimeters.json`,
`migration_installed.json`, `model_playback_installed.json` and their background
logs. Tools: `test_control_rig.py`, `test_control_migration.py`,
`test_control_model_playback.py`, `build_control_rig_review.py`.
