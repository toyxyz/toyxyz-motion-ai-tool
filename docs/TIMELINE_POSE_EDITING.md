# Edit native pose keys in the Motion Timeline (v0.25.0)

The **Keyframes** row now selects, moves and deletes the main SOMA's real user pose keys. It remains an aggregate view of the authoring Action's current slot; generated NLA keys are excluded. A diamond represents every unmuted SOMA transform key at that frame, across keyed bones. Editing a diamond edits that whole pose-time group rather than only the currently selected bones.

| Action | Control |
|---|---|
| Select one pose | Click its diamond |
| Add/remove a pose from selection | Shift-click |
| Subtract a pose | Ctrl-click |
| Box-select poses | Drag empty space in the Keyframes row; Shift adds and Ctrl subtracts |
| Box-select with a shortcut | B, then drag; the row under the pointer or the current edit target determines the domain |
| Move selected poses | Drag a selected diamond, then release |
| Move with a frame offset | G, move the pointer or type an integer, then Enter or left-click |
| Cancel a move | Esc or right-click |
| Delete selected poses | X for confirmation, or Delete immediately |
| Select/deselect/invert | A / Alt+A / Ctrl+I while the Keyframes row is active |
| Frame all/selected poses | Home / Numpad Period while the Keyframes row is active |

Clicking a motion block switches editing back to motion blocks. Key selection and block selection are independent so the generation selection is retained while editing constraints. X/Delete prefer actual selections in the active domain. If that domain has no selection, they use the other domain's selected items instead of failing because of stale row focus. Both shortcuts explicitly reset automatic targeting; a previous explicit pose/block deletion is not reused. The **Key** header menu shows a key icon while pose editing is active and provides explicit Move/Delete Pose Keys commands; the **Block** menu explicitly deletes blocks. Scrubbing still uses the ruler and existing playback controls. Selecting/moving keys does not move the playhead. Right-clicking a key selects that frame and opens its constraint-type dialog without scrubbing.

## Data behavior

- Moving shifts actual native key times. Values, interpolation and manual handle offsets are retained; Blender recomputes automatic handles normally. Curves are sorted during each preview, including when moving across unselected keys. Full Body and compound annotations such as LH+RF follow the pose groups. The saved Action annotation is committed only when the move finishes.
- A move that would land directly on an existing stationary pose is rejected and restored. Distinct poses are not silently overwritten. Locked F-Curves or channel groups, linked read-only Actions, NLA Tweak Mode and generated Actions are protected.
- Delete removes only the selected native pose-time groups from the authoring Action slot and removes their constraint annotations. Reinserting a key at a deleted time defaults to FB. Object/custom-property channels, other Action slots and generated NLA curves remain intact.
- Existing generated motion is retained. Editing the correction Action changes its native contribution normally; use Generate Motion to regenerate AI motion with the updated constraints. Only keys inside the selected blocks are generation targets.
- Automatic application of completed model results waits while a modal pose move is active. Existing stale-key/type validation still prevents applying a result to changed constraints.
- Native Undo/Redo and `.blend` save/reopen retain keys and annotations. Motion-block transforms and their linked NLA editing remain available.

Movement uses integer scene-frame offsets. Native subframe keys can also be moved while retaining Blender's floating-point time precision; generation continues to require whole-frame targets.

## Validation

`test_delete_timeline_target.py` reproduces the stale empty pose-domain error while a motion block is selected. It verifies block/NLA deletion without touching user keys, pose deletion without touching selected blocks, explicit targets, fallback in both directions and the X/Delete automatic-target and confirmation flags. Reports are `results/blender_bridge/delete_timeline_target*.json`.

`build_tools/test_timeline_pose_edit.py` uses separate Blender 5.2.3 background processes, real RNA and synthetic mouse/keyboard events. It checks single/group drags across other keys, exact retained pose values, cancellation, box selection, numeric G input, collision/lock protection, compound annotations, other-slot/object-channel isolation, actual move/delete operators, native Undo/Redo, delete-all/reinsert, subframe previews and save/reopen. Generated NLA data and motion block bounds are compared before and after editing. The test also checks that automatic result application waits during a move.

Reports: `results/blender_bridge/timeline_pose_edit.json` and `timeline_pose_edit_installed.json`. Existing `block_selection.json`, `pose_constraint_ui.json` and `layered_corrections.json` cover the block editor, constraint lifecycle and native correction playback regressions. The user's GUI is not automated; manual interaction/layout acceptance remains separate.
