# Foot Contact removed (v0.31.0)

The user requested removal of the block **Modifiers** menu and experimental **Foot Contact** feature on 2026-11-08. Do not restore or extend the feature without a new user request.

Removed from the active addon/runtime:

- Modifier UI, property types, add/remove operators and viewport foot-target drawing.
- Surface sampling, alternating automatic foot goals and reference-leg IK.
- Procedural foot input generation, worker integration, capability flag and result-error UI.
- Experimental gait probe tools and feature-only tests; their sources are historical snapshots.

The archived implementation and historical documentation are under [development/removed_foot_contact/v0.30.0](../development/removed_foot_contact/v0.30.0/). No archived module is imported by the active addon or runtime. Existing numerical reports and generated review files are retained as evidence, not supported authoring workflows.

## Existing scenes

Generated Actions/NLA clips, user pose keys, SOMA skinning, terrain meshes and curve objects remain unchanged. The addon reads an old modifier's serialized properties once, recovers its enabled route into the block's ordinary **Path Curve**, and retains its old metadata without registering any modifier type. Subsequent changes to Path Curve remain user-controlled. Curve Start (%) and shared-route traversal remain supported.

Native manually authored Left/Right Foot key constraints remain supported. The removed feature is procedural surface-foot placement, not the models' native constraint support or their ordinary foot-skating postprocessing. Old procedural `foot_contact` job payloads are explicitly rejected; new generation must use the updated addon. Pending legacy procedural results are skipped rather than newly applied. Previously applied clips keep playing as native Blender animation.

Restart Blender and the companion app to unload the old classes, draw callbacks and resident worker code.

## Verification

`build_tools/test_foot_contact_removed.py` loads the supplied `foot_contact_test_01.blend` read-only. It verifies absent UI/classes/operators, one-time curve recovery, no new automatic foot payloads, rejection of old payloads and continued native manual foot constraints. It compares pelvis/ankle/toe-base positions at all 318 saved scene frames against the pre-removal diagnostic and checks the original file hash. Source results are in `results/blender_bridge/foot_contact_removed.json`; installed results use `foot_contact_removed_installed.json`.

Existing curve timing, coordinate conversion, shared-route and native keyframe UI regression tests also apply. Numerical preservation does not imply approval of the historical gait quality.
