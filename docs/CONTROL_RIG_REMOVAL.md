# Native SOMA bones restored

Version 0.40.0, 2026-11-09. The user withdrew the added control rig and explicitly
did not request compatibility with its animation.

New actors contain the original 77 SOMA bones and the preview mesh. Pose and key
the native bones with Blender's normal tools. End and Eye bones remain hidden;
the armature uses Octahedral display. The actor roster, independent motion
timelines, selected-block generation, pose-target previews, native NLA correction
layers and Clear Motion remain available.

The FK/IK control bones, master/hips widgets, poles, parent-space controls, custom
key insertion, interaction handlers and Python following code are removed. The
installer removes their four deployed modules and cached bytecode. No replacement
solver or toolbar tool is installed.

After restarting Blender, old tool-marked actors discard the added control bones,
their constraints, drivers and unused widgets on a safe update. The actor, SOMA
rest skeleton, mesh and prompt blocks remain. The visible static pose is retained.
Controller-channel authoring Actions are detached and controller-based generated
clips are removed; they are not converted or baked onto SOMA. Native SOMA Actions
and generated native strips are retained. Historical Action datablocks are not
globally purged. No existing user blend file is saved automatically.

Cleanup waits during Edit Mode, NLA Tweak Mode, a modal operation or generation.
Actors in inactive scenes are cleaned when their scene becomes active.

## Verification

Blender 5.2.3 background checks cover new 77-bone actors, mesh creation, independent
actor workspaces, native keys and generation requests. Two saved controller
fixtures are cleaned and saved/reopened as separate review copies; source fixture
hashes stay unchanged. Tests assert the original rest fingerprint, no remaining
controller constraints/drivers/widgets, and no controller-based active clips.

The existing Clear Motion regression covers Kimodo, ARDY and MotionBricks native
clip application/removal, user keys, another actor's live edits, Undo/Redo and
save/reopen. These checks exercise recorded or synthetic result application;
they do not establish new model inference quality or interactive gizmo usability.

Reports: `results/control_rig_removal/` and
`results/blender_bridge/clear_motion*.json`. Historical control modules and their
hashes are retained only in `development/removed_control_rig_2026-11-09/`.
