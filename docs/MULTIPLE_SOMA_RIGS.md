# Multiple SOMA Rigs

Version 0.33.0 adds a **SOMA Rigs** list to the Motion AI sidebar, available in both the 3D View and the dedicated Motion Timeline.

Version 0.36.1 uses `actor_01`, `actor_02`, etc. for new rig objects and armature
data, with `actor_01_mesh` for the matching preview body and `actor_01_skin` for
its hidden skin helper. Number allocation skips occupied object/data names.
Existing tool-default rig/mesh names migrate once on refresh or file load;
custom rig names and later manual renaming are retained. Selection, native
keys, blocks and NLA use the same objects and persistent identities.
An installed-addon background smoke check created `actor_01`/`actor_02` and their
matching bodies, migrated a legacy name, and retained its native frame-12 keys,
rig UUID, body parent and the other active rig. A subsequent custom name stayed
unchanged. Evidence: `results/blender_bridge/actor_naming_smoke.log`.

1. Click **Add SOMA Rig** to create an independent armature and skinned preview at the 3D cursor. Each new rig starts with one motion block.
2. Select a SOMA armature directly in the 3D View or Outliner, or select it in **SOMA Rigs**, to edit its motion timeline. Native active-armature selection automatically updates the list. List selection also selects the rig in the viewport when visible. Names in the list can be edited directly.
3. Add/move/delete blocks, set prompts and curves, author pose keys and use **Generate Motion** for that rig.

**Add SOMA Rig** is the single creation button: it adds both the armature and its preview mesh together. Native Blender object deletion removes a missing rig from the list on refresh. Selecting a rig does not hide other characters, so all their native NLA animation can play together.

The adjacent **− Delete** button removes the selected rig, its owned preview body/skin helper and its roster workspace together. **Ctrl+Z** restores them, including native pose keys and generated NLA. Only unused private mesh/armature/skin-node data is cleaned up; shared data, Actions and other characters are not purged. Unrelated child attachments are retained at their world transforms. The next remaining rig becomes editable; deleting the last rig leaves an empty list and timeline. Finish or cancel a generation operation on the rig before deleting it; another rig's running operation does not block deletion.

`results/blender_bridge/delete_soma*.json` records native deletion, another character's pose keys/NLA preservation, shared data and attachment preservation, Undo/Redo and last-rig cleanup tests.

For a cleaner authoring display, `*End` bones and `LeftEye`/`RightEye` are hidden on new rigs and existing rigs during their first refresh after this update. A selected auxiliary bone is deselected when hidden. The defaults apply once, leaving subsequent manual visibility choices intact. These bones remain in the SOMA hierarchy, model requests, skinning and animation data. Full Body pose-target overlays also omit the corresponding branches; native hand/foot constraint points still represent the actual model goals.

## Independent data

Each roster entry owns its blocks and persistent block IDs, selected blocks, generation parameters (including encoder precision), user pose Action/constraint annotations, last applied result, display options and timeline zoom/pan. Armature data, preview skin helpers and generated NLA strips belong to the corresponding character. Playback uses native Blender Actions/NLA for every rig.

Changing the list selection changes the one dedicated timeline's editing target. Pose-target overlays show only the selected rig's selected blocks. The old scene-level settings remain a compatibility source; active rig settings are resolved through the roster, not copied back and forth when selecting a character.

Direct armature selection is detected on the addon refresh (about 0.2 seconds). With multiple objects selected, the active selected SOMA armature determines the editing target. This synchronization preserves native object selection and Object/Pose/Edit Mode; selecting unrelated objects or deselecting everything retains the current motion workspace. Generate Motion also checks native armature selection immediately before starting. Pending operations remain bound to their original rig.

Idle refresh leaves unchanged roster properties untouched. An audit found repeated assignments of the current active index even with no selection changes; these no-op writes are removed. `idle_rig_sync*.json` verifies zero selection-update callbacks during idle polling, preserved active bone/pose and inactive timeline mouse handlers in the 3D View. This is not an interactive gizmo hit-test or proof of the reported clicking issue's cause; native gizmo settings and viewport keymaps are not changed.

Existing single-rig scenes migrate once: their original block IDs, curves, generation settings, native pose keys and generated NLA are retained. The source `.blend` file is not rewritten automatically. Save the scene normally to persist the roster. Removed Foot Contact and Smart Primitive features remain removed.

## Generation and selection changes

The companion connection and resident GPU models are shared. Generation remains one operation at a time, including a selection spanning several models. Switching the selected rig while generation or connection is pending does not redirect the job: auto-application and later sequence groups use the original rig identity. The sidebar identifies the owner when another rig is being generated. A removed original rig causes a clear application error; its result is never applied to the next rig in the list.

Other rigs can keep playing and can be edited while the shared generation operation runs. Starting another job requires the current operation to finish or be cancelled. Constraints, previous-motion history and curve grouping are resolved within the owning rig's blocks.

## Validation

Actual Blender 5.2.3 background tests create two distinct armatures and body previews, author different native keys and constraints, switch timelines, and import separate synthetic model results into native NLA. They verify original-rig auto-application while another character stays selected, linked block movement/deletion, pending auto-connect, mixed Kimodo-to-ARDY sequence continuation, independent parameters and views, and save/reopen. The existing user scene also migrates without changing the source file; all 318 saved native frame samples retain their previous pelvis/foot positions.

These are integration and playback checks using synthetic results; this feature does not change model inference or claim improved generated motion quality. Existing curve timing, compound constraints, native key editing, automatic connection and skinned preview regressions also pass. Reports are `results/blender_bridge/multi_rig.json` and `multi_rig_installed.json`.

Restart Blender after installing the update. The companion app needs no restart.
