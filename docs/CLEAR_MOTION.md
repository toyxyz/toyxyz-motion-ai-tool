# Clear Motion

Select one or more motion blocks in the selected rig's Motion Timeline, then click **Clear Motion** directly below **Generate Motion**. The selected blocks do not need to be contiguous or use the same model.

Clear removes all generated clips linked to those block IDs, including inactive legacy versions. It retains the blocks themselves, prompts, curves, timing, selection, generation settings and native user pose keys/constraint annotations. It does not restore a previous generated take. Blocks with no generated result are left in place; the button is disabled when none of the selected blocks has generated motion.

The user's native authoring Action, key times/values, interpolation and handles are retained. Clear does not bake the displayed generated pose into that Action or create extra user keys. Once all generated clips are cleared, playback contains the user's animation alone. Other generated blocks and other rigs remain available.

Unkeyed bone channels return to the saved pre-generation authoring base. New generations record that base before their first result is applied. Older scenes without this saved base use the SOMA rest basis for unkeyed channels; user pose keys are still retained. After the final generated clip is cleared, a later generation captures a fresh authoring base.

## Native playback

Clearing a block retains its timeline entry and explicitly marks it as having no generated result, preventing NLA synchronization from interpreting the operation as block deletion. If leading authoring blocks are empty, the earliest remaining generated strip uses **Hold Forward**, so its first pose does not pre-hold over the cleared interval. Its final pose still holds after the strip. A preceding generated block can continue holding its final pose through an empty gap, just as it did before the cleared block was generated.

Unrelated NLA tracks and user Actions are retained. Unused private generated Actions may be removed after their linked strips are cleared; shared or explicitly retained Actions are not purged. The completed result for this rig is dismissed to prevent reapplying it accidentally. Clear needs no connection to the companion and does not unload resident GPU models.

Finish/cancel generation for the same rig, and exit Edit/NLA Tweak Mode, before clearing. A different rig's generation is unaffected. **Ctrl+Z** restores the cleared motion and **Redo** clears it again. Save/reopen retains the cleared state.

## Validation

Blender 5.2.3 tests cover Kimodo, ARDY and MotionBricks clips; selected-only and noncontiguous selections; inactive legacy versions; native key/handle/annotation preservation; unchanged unselected clips; no future pre-hold; Undo/Redo; save/reopen; no-key neutral restoration; preservation of another rig's live unkeyed edits; and regenerate/clear cycles. These integration tests use synthetic results and do not change or evaluate model inference quality.

The source Action key data is checked for exact equality. The final clear matched the authoring-only animation samples with zero measured difference. The partial-clear test, which retains other NLA clips, observed a maximum sampled matrix-entry difference of about 0.000106 against a fully muted reference; authored key poses and root transforms were checked separately at tighter tolerances. Reports are `results/blender_bridge/clear_motion.json` and `clear_motion_installed.json`.

Restart Blender after updating. The companion app needs no restart.
