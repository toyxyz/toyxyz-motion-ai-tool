# Blender Addon: toyxyz_motion_ai_tool

Separate [FK and IK controls](SPLIT_CONTROL_RIG.md) support automatic pose matching. Select an actor and click **Add Control Rig** below the **SOMA Rigs** list.

Actors can be animated with their native SOMA bones or with the optional FK/IK controls.

**Clear Motion**, below Generate Motion, removes generated results for selected blocks while keeping their native user pose keys, block settings and prompts. It supports multiple selections, native Undo/Redo and saved scenes. See [clearing generated motion](CLEAR_MOTION.md).

The top app control switches from **Start** to **Stop** while the companion is running and returns to **Start** after shutdown. The small **chain icon** beside it reconnects without launching another process. The separate bottom Stop App button has been removed; **Release GPU** remains available. Restart Blender to load the updated controls.

Use the add-on's **Port** preference to change the local connection port. See [changing the companion port](README.md#change-the-companion-port).

Requires Blender 5.2 or later. The timeline and block transitions were checked with Blender 5.2.3 LTS and 5.3.0.

**MotionBricks v0.16.2 correction:** canonical SOMA rotation deltas now convert to/from the native joint frames of MotionBricks' official USD skeleton. Earlier bridge versions matched endpoints but fed incompatible rotation features to the model, causing severe intermediate joint motion. See [joint-frame diagnosis and replay evidence](MOTIONBRICKS_JOINT_FRAME_FIX.md). Affected existing clips must be regenerated; user pose keys are preserved.

## Workflow

New SOMA actors start with an **ARDY** block. **Add Block** inherits the active block's model when a block is already active.

For installation, encoder selection and model access, see the [Windows installation guide](README.md).

### Block Transitions

Generate touching ARDY blocks one at a time with **Motion Post-Processing** enabled to use shared contact cleanup when ARDY predicts a foot contact across the join. Use the matching 0.46.4 companion and generate the preceding block with that version first. Blender stores the result in **Motion AI · Block Transitions** in the NLA Editor. See [ARDY transition behavior and eligibility](ARDY_BLOCKS.md#shared-contact-cleanup).

### Control Layers

Click **Add Control Layer** in the Motion Timeline header. The new layer appears above the Motion row and spans the selected blocks. With no selected block, it starts at the playhead and spans two seconds. Each actor can have several layers. Overlapping layers combine with the generated motion in their displayed stack order.

Click a layer to edit its own keys in Blender's Timeline or Dope Sheet. Pose and key the actor within the layer's range. Click the layer again or select a motion block to return to the actor's main pose keys. Drag a layer horizontally to move its keys and playback range together. Use the eye button beside **Add Control Layer** to mute or enable the selected layer. With **View > Channels** on, each layer also has an **On/Off** control in its row. When rows extend beyond the editor, drag with the middle mouse button vertically to pan.

Drag a layer's left or right edge to trim or extend its playback range. Resizing preserves keyframe timing and uses a minimum duration of one frame. Keys outside the trimmed range remain in the Action and become available again when the range is extended. Press **Esc** or right-click during a drag to restore the original range.

Press **X** or **Delete** in the Motion Timeline to remove the selected layer. Layer keys are stored in separate native NLA Actions and affect playback as corrections. Generation continues to use the main pose keys and keeps the layers available for playback after regeneration or **Clear Motion**.

### Export FBX

Select an actor in **SOMA Rigs** and click **Export FBX** below **Generate Motion**. The export samples the evaluated pose on each frame across the active animation range. This includes generated motion, user pose keys, enabled control layers and FK/IK switches. Muted layers are excluded.

The FBX contains one animation clip on the selected actor's 77-bone SOMA skeleton with the default SOMA rest pose. The clip starts at frame 1 at the scene frame rate. The source actor keeps its control rig, motion blocks and layers for further editing.

### Agent Control

Use **Enable Agent Control** in the **Motion AI** sidebar to let a local agent send structured commands to the open scene. The commands run through Blender and Motion AI. See the [Agent Control guide](AGENT_CONTROL.md) for the CLI and examples.

Version **0.33.0** adds **SOMA Rigs**: click **Add SOMA Rig** for another character, then select a rig in the list to edit its independent blocks, prompts, pose keys, generation settings and NLA motion. Pending generation stays bound to its original rig when selection changes. Existing single-rig scenes migrate automatically. Restart Blender; the companion needs no restart. See [multiple rig workflow](MULTIPLE_SOMA_RIGS.md).

Version **0.32.0** adds **Show Pose Targets**: selected motion blocks display their actual input constraints directly in the 3D viewport. Full Body targets use blue skeletons; hands, feet and root goals use distinct colored spheres. No scene objects or animation keys are added. Display options are in Advanced. Restart Blender; the companion needs no restart. See [pose target preview](POSE_TARGET_PREVIEW.md).

Version **0.31.0** removes the block Modifiers menu and experimental Foot Contact feature. Existing generated NLA clips, manual pose keys and scene objects remain intact. Old modifier curve assignments are recovered into the ordinary Path Curve field; automatic foot goals, previews, terrain sampling and reference IK are no longer used. Manual foot key constraints and Curve Start (%) remain supported. See [removal details](FOOT_CONTACT.md). Restart Blender and the companion after updating.

Version **0.29.0** adds **Curve Start (%)** below Path Curve and in the block edit popup. Use 0 for the block beginning, 50 for its midpoint, or 100 to target the curve start at the last sample. The percentage stays unchanged when the block moves or changes length. Touching same-model/same-curve blocks continue the shared route. See [curve timing](KIMODO_PATH_CURVES.md). Restart Blender and the companion to load the update.

Version **0.28.1** removes the Constraint Types box that appeared/disappeared at keyed playhead frames in the sidebar. Use the native key diamond's right-click dialog in the Motion Timeline for constraint types, root heading and root height. Existing annotations and generation behavior are retained. Restart Blender to load the UI change.

Version **0.28.0** adds an official SOMA body mesh for preview. Click **Create SOMA Rig + Mesh** to create both or to add the mesh to an existing input rig. Repeated clicks reuse the existing rig and mesh, preserving pose keys and generated NLA. **Show SOMA Mesh** controls body visibility; the rig remains available for editing. Native Armature/Geometry Nodes deformation matches official skinning without a second armature or per-frame Python. Saved scenes remain playable without the addon or external app. See [details and numerical/render verification](SOMA_PREVIEW_MESH.md).

Version **0.27.0** adds **Constrain Root Height** next to Root Heading at native **Root Position (2D)** keys. It defaults off, reads the composed visible hips height and does not constrain the rest of the body pose. Height and heading are independent: labels are **R2**, **R2H**, **R3** or **R3H**. Curve elevation remains ignored; height comes from the keyed pose. Both Kimodo and ARDY use their native conditioning channels through a bridge-local adapter; MotionBricks retains Full Body targets. Independent height is a soft model goal whose measured accuracy can be poor for large changes. The menu states this limitation and automatic application reports the maximum height deviation. Restart Blender and the companion after updating. See [height controls, measured limitations and validation](KEYFRAME_CONSTRAINT_TYPES.md#optional-root-height).

Version **0.26.0** adds **Constrain Root Heading** beneath a native key's **Root Position (2D)** selection. It defaults off, uses the keyed visible facing direction and shows **R2H** when enabled. Kimodo and ARDY can combine it with endpoint goals and a Path Curve; position and facing may differ from the curve tangent. Heading remains a model condition rather than an exact rotation pin. Update/restart Blender and the companion app for this feature. See [controls and validation](KEYFRAME_CONSTRAINT_TYPES.md#optional-root-heading).

Version **0.25.0** makes the dedicated timeline's **Keyframes** row editable. Click/Shift-click or box-select real pose keys, drag or use **G** to move them, and use **X/Delete** to remove them. Compound constraint annotations move/delete together with the native keys. The last active row determines keyboard selection/deletion; the header has explicit **Key** and **Block** commands. Generated NLA motion and block timing remain independent. See [controls, preservation and validation](TIMELINE_POSE_EDITING.md).

Version **0.24.1** removes Smart Primitive buttons, edit mode, temporary-rig creation and automatic route generation. This workflow focuses on offline animation correction with native pose keys, motion blocks and NLA layers. Old boxes, stored poses, draft rigs and generated native animation are retained when opening existing scenes. A one-time compatibility step restores main visibility after an old primitive edit session. See [removal details](SMART_PRIMITIVES.md). Restart Blender after updating; the companion app needs no restart.

Version **0.23.0** adds multi-select **Constraint Types** at each native SOMA key. Combine hands, feet and root goals in the sidebar or the key diamond's right-click dialog; labels show combinations such as **LH+RH** or **LH+RF**. Full Body remains exclusive and is restored when the last partial goal is deselected. Kimodo and ARDY receive separate same-frame targets from one composed pose; MotionBricks still requires FB. Single-type saved metadata remains compatible, and the partial-target FK-pop fix applies to combinations. Restart Blender to load the addon update; the companion does not require a restart. See [controls, persistence and real-model verification](KEYFRAME_CONSTRAINT_TYPES.md).

Version **0.22.1** fixes a one-frame FK pop at partial constraint keys during NLA result application. Hand/foot/root goals retain the generated solution instead of restoring unrelated old local rotations at that single frame. Full Body local-channel priority and source correction keys remain intact. Existing affected clips need regeneration after restarting Blender. See [diagnosis and same-result replay](PARTIAL_CONSTRAINT_FK_POP_FIX.md).

Version **0.22.0** adds per-native-key **Constraint Type**. At a keyed playhead frame, choose Full Body, Left/Right Hand, Left/Right Foot or Root Position (2D) in the sidebar. The dedicated timeline's key diamonds also have a right-click type menu and compact **FB/LH/RH/LF/RF/R2** labels. Full Body remains the default. Kimodo/ARDY consume these mixed types; MotionBricks explicitly requires FB. Annotations follow native keys and persist in the authoring Action slot. See [controls and lifecycle](KEYFRAME_CONSTRAINT_TYPES.md).

Version **0.21.0** adds **ARDY** to block Model choices. It autoregressively generates exactly the selected block lengths, with changing prompts across blocks, ordinary SOMA pose keys, shared Path Curves and an optional preceding-clip history. Results use the existing automatic native NLA/correction-layer workflow. ARDY has a 30 Hz model rate, a 60-frame prediction horizon and 4-frame tokens; these internal sizes do not cap the total block duration. Short/non-token-aligned outputs are padded internally then trimmed. The minimum is one model output frame; there is no model duration maximum and ARDY-only operations have no 60-second cap. **Advanced** uses separate ARDY denoising steps (1–10, default 10). See [ARDY support and validation](ARDY_BLOCKS.md).

Version **0.19.0** adds **Transition Overlap (30 FPS)** to Kimodo block settings and the double-click editor. Default **5** controls each incoming transition in model frames at 30 Hz (5 means about 0.167 seconds, or 10 scene frames at 60 FPS). Since **v0.20.0**, the first selected Kimodo block also uses the actual tail of an adjacent existing generated clip, including when generating just one block. Existing predecessor Actions and user keys remain intact; only selected intervals are applied. Without an adjacent result, there is no history overlap. MotionBricks has no overlap input and retains its fixed four-pose context. See [transition controls and verification](KIMODO_TRANSITION_OVERLAP.md).

Version **0.18.0** adds **Path Curve** to each Kimodo block, in the sidebar and Edit Motion Block popup. Since **v0.18.1**, touching enabled Kimodo blocks with the same Curve object share one traversal across their total duration. Partial regeneration retains the block's assigned section; gaps or a different curve end the group. Select a Blender Curve object, enter a walking/running prompt and generate normally. A blank Path Curve retains the previous behavior. See [curve workflow and validation](KIMODO_PATH_CURVES.md).

Version **0.17.0** adds a native percentage progress bar under Generate Motion. Kimodo reports completed denoising iterations across all blocks in its model run. MotionBricks reports completed pose-to-pose transitions; one TensorRT call is a single operation and has no internal percentage callback, so very short generations may jump between values. Active job status is polled about every 0.15 seconds and displayed on Blender's main thread. Model/text-encoder loading remains at 0% with its stage text; percentages are not an elapsed-time estimate. Mixed-model operations weight each run by its selected block count, retain overall progress across model changes, and reach 100% only after the last automatic Blender application. Failures/cancellation retain partial progress.

Block names are assigned internally; the persistent UID continues to manage links. The sidebar and Edit Motion Block popup have no name input. Double-click edits Prompt, Path Curve and Transition Overlap (Kimodo) or Notes (MotionBricks). Existing saved names remain as metadata and generated NLA labels.

Since **v0.36.2**, **Generate Motion** uses the same Start/connect path as **Start** when disconnected or connected to another scene. It launches a stopped companion, reuses an existing compatible app and waits for the health/lifetime handshake before sending the originally selected blocks exactly once. Temporary connection refusal while the app starts displays **Waiting for the companion app to start and connect...**, instead of a raw socket error. The startup connection timeout is 60 seconds; timeout clears the progress bar and pending request. Cancel, changed block settings or loading another file prevent later submission. An already connected scene submits directly. Evidence: `generate_auto_connect_installed.json`, including an actual hidden companion startup on an isolated port with submission intercepted before any model load; historical real GPU/automatic application is in `auto_connect_motionbricks.json`.

**Start** checks the configured port and connects to a compatible companion from the configured installation. If the companion is stopped, Blender launches it and connects. The chain icon requests a connection to an already running companion. Repeated clicks during startup reuse the pending launch.

1. Enable the add-on and leave **External App Folder** blank for automatic detection. Set it to select an alternate installation.
2. In the 3D View sidebar, open **Motion AI**, click **Start**, then click **Add** under **SOMA Rigs**.
3. Click **Open Motion Timeline**. The dedicated editor is also available in the editor-type selector. Native Blender Timeline headers are unchanged.
4. Click **Add Block** in the dedicated timeline header. A new block inherits the active block's model and appends after the last motion block, regardless of model. Choose **Model** on the active block to switch between Kimodo, MotionBricks and ARDY. All use one shared motion row.
5. Click a block to select it; **Shift-click** toggles additional blocks. Drag empty graph space to box-select intersecting blocks. Drag a selected block body to move the selection together, or drag an edge to resize the active block. Edges snap to other motion blocks, including different models; press **Shift during the drag** to bypass snapping. End frames are exclusive. Block duration limits still constrain resizing; the sidebar has no length or Start/End controls.
6. Double-click a block to edit its prompt or notes and, for Kimodo or ARDY, an optional **Path Curve**. You can also edit the active block's settings in the sidebar. Block names are managed automatically. **X** confirms deletion. **Delete** removes selected blocks and their linked NLA clips immediately. **Ctrl+Z** undoes edits.
7. Pose SOMA bones and insert ordinary Blender keys directly, including while viewing generated motion. No mode switch is needed. The basic Timeline shows those keys; the dedicated timeline's Keyframes row represents the same real keys. Click/Shift-click or box-select its diamonds, drag or use G to move them, and use X/Delete to remove them. Native Blender key editing remains available. There are no separate pose records.
8. Select the desired blocks and click **Generate Motion**. One selected block generates alone; multiple selected blocks generate as a sequence in time order. All selected blocks must be enabled and touch without gaps/overlaps. Mixed selections across all three models are supported. Same-model runs use a shared sequence request; model changes wait for automatic NLA application before requesting the next run with the inherited endpoint. Unselected neighbors are never added automatically, whether already generated or not. Select at most 32 blocks; the 60-second operation cap applies unless every selected block is ARDY.
9. The completed motion is applied automatically on a new native NLA playback track containing the current timeline, on the same SOMA armature. No Apply Result click is needed. The user Action combines with the generated base at every frame.

## Block selection and one generation command (v0.13.0)

### Unified motion row and mixed models (v0.16.0)

Kimodo and MotionBricks blocks share one row. Model names remain in block labels and the active block's Model selector. A second row displays the SOMA input Action's actual pose keys, including native selected/unselected theme colors. Generated dense NLA keys never appear there or become new pose targets. Native key insertion, movement, deletion and selection are reflected automatically. Keys are independent of block movement. There is no duplicate pose collection and this display does not replace Blender's native key-editing tools. Marker data is cached briefly for drawing so playback does not scan every pose curve on each frame.

The sidebar no longer contains Allowed Length or per-block Start/End controls. Manage timing by dragging block bodies/edges in the timeline; model-specific duration bounds still apply. Scene playback-range controls in Blender's reused header remain native.

One Generate Motion command accepts touching mixed-model selections. The addon splits the selection into chronological runs of a single model. After each result is automatically applied, the next run reads the preceding composed pose, including root position, from native NLA. MotionBricks also receives four recent context poses. Explicit native Start keys still take priority. Cancel or generation/application failure stops pending runs; successful earlier runs remain applied. Changing a sequence block's timing, model, prompt or Enabled state stops further submission rather than using stale settings. No other selected or unselected blocks are silently added. Repeated jobs for the same model reuse its resident worker; a model change replaces the motion worker while retaining the shared encoder.

Evidence: `unified_motion_timeline.json` covers actual GPU marker colors, native key deletion, one-row hit testing, removed sidebar bounds and queue cancel/failure/edit behavior. `mixed_generation.json` covers real Kimodo -> MotionBricks -> Kimodo GPU jobs, both inherited boundary poses, source Action/slot/keys, one SOMA, one playback track and an untouched unselected neighbor. These numerical and rendering checks do not establish general motion quality or manual UI acceptance.

Version **0.15.0** removes MotionBricks boundary-key requirements. Native SOMA pose keys can be anywhere inside the selected blocks. The final key is the stop target at its authored time, rather than being stretched to End - 1; unused time before the first key and after the last key holds their poses. For example, keys at frames 0 and 54 in a block [0,116) connect to the target at frame 54 and then hold it. Neither frame 115 nor interior block boundaries need extra keys. Block bounds and user keys remain unchanged. Without preceding generated motion, at least two pose keys are needed; with inherited motion at Start, one destination key is sufficient. Keys closer than one 30 FPS sample (two scene frames at 60 FPS), or mapping to the same model sample, produce an error listing the pair. The sidebar wraps the complete status message; background health polling preserves local validation errors. Synthetic Blender regression evidence: `results/blender_bridge/motionbricks_key_timing.json`; real model/automatic NLA evidence: `results/blender_bridge/motionbricks_free_targets.json`.

**Generate Motion** replaces both **Generate Sequence** and **Generate Active Block Only**. The submitted block IDs come only from the current selection. Empty selection, disabled selected blocks and gaps/overlaps produce a clear error rather than silently expanding or skipping blocks. Mixed models are supported in v0.16. Existing native motion outside the submitted selection remains in the playback track.

Click selects one block; Shift-click toggles selection. A click on an already-selected block collapses to that block on release; dragging it retains and moves the group. Drag empty graph space to box-select any intersecting blocks; Shift-box adds and Ctrl-box subtracts. **B** starts box selection even over a block, **A** selects all, **Alt+A** deselects, and **Ctrl+I** inverts. Escape/right-click restores the previous selection and cancels a drag. The active selected block has a stronger border and controls the prompt/settings sidebar.

The top frame ruler still scrubs the playhead. Empty graph space now selects blocks instead of scrubbing. The active block's Enabled setting remains in the sidebar; the duplicate management list was removed in v0.14. Adding a block selects only the new block. Frame Selected fits the full selection. Delete/X and group movement keep linked NLA clips synchronized. Selection is saved in the blend file and participates in native undo/redo. Older files initially select only their active block.

## Timeline management and selection appearance (v0.14.0)

**Add Block** is a direct button in the dedicated timeline header. The duplicate sidebar block list and its Add/Delete row are removed. Select and manage blocks in the timeline; use X/Delete or **Block > Delete Selected Blocks** to delete. The sidebar keeps Enabled, model, prompt and generation settings. Timing is managed in the timeline and names are assigned internally.

Box selection uses the native gesture appearance rather than the block highlight color: a one-pixel alternating gray/white dashed outline with a subtle neutral fill. The pattern follows Blender's [gesture drawing source](https://github.com/blender/blender/blob/main/source/blender/windowmanager/intern/wm_gesture.cc): 8-pixel dash cycle, half gray/half white and a 5% white fill. The blue filled rectangle is removed. Screen appearance remains subject to manual user review; no user GUI is automated.

Version **0.14.1** fixes the fill becoming opaque after text labels were drawn. Blender's font renderer ends with blending disabled; each subsequent canvas primitive now explicitly enables alpha blending before drawing. The 5% fill remains translucent over both the background and grid. `selection_alpha.json` verifies this using actual headless GPU framebuffer pixels in the installed Blender, including confirmation that native text drawing resets the blend state. This does not automate the user's GUI.

## Resident GPU models (v0.11.0)

See [current measurements by model and encoder](PERFORMANCE.md) for VRAM, first-run loading, and warm generation times.

Successful generation keeps the selected motion model in an app-owned resident GPU process. Repeated Kimodo jobs reuse one motion model and repeated MotionBricks jobs reuse one TensorRT engine, pose buffers and CUDA graph. The first job loads the model; later jobs reuse it. Selecting a different engine for the next generation stops the old motion process before starting the new one. The shared text encoder stays available across motion-engine changes.

Changing BF16/INT8/NF4 replaces the active text encoder profile while retaining the resident Kimodo motion weights; the worker refreshes its encoder connection for each job. **Release GPU** stops the motion worker and all matching shared encoders from this portable installation, including a compatible service left by an earlier session. Process identity and executable/entry paths are checked before an adopted service is stopped. Services from other installations are not terminated. The next generation loads the required models again. Release is rejected while a generation is active; finish or cancel it first.

Cancellation or a GPU worker failure stops that worker so an interrupted CUDA/TensorRT context is not reused. The following job starts clean. Closing the companion app also closes its resident worker. Closing only the dashboard tab does not unload models. The dashboard and Blender's **GPU Model** label show the resident engine. Restart the companion app to apply this service update; this release keeps the existing HTTP protocol and result format compatible.

`resident_motion.json` verifies reuse with the same PID and exactly one motion weight load, engine switching, BF16-to-INT8 encoder replacement without reloading Kimodo, explicit release and reload. A short same-request test with the encoder already loaded measured end-to-end app job times of **7.27 s cold / 0.31 s warm** for Kimodo (60 output frames, BF16, 10 denoising steps), and **1.88 s cold / 0.11 s warm** for MotionBricks (58 output frames). These timings exclude Blender polling/application and are fixture-specific. First use after Release GPU also includes text-encoder loading when required.

## Single generated playback track (v0.12.0)

Successful application keeps the current timeline's generated clips together on one playback track and removes obsolete plain, muted tool playback tracks. Older versions kept those rows as generation history; they are unnecessary for current playback. Existing files receive the same cleanup during addon initialization. Previous results can still be restored through native Undo rather than accumulating disabled NLA rows.

Cleanup runs after successful application, preserving failure rollback. The current track and its shared Actions, user correction Action and absolute-key backup remain. Unrelated/mixed tracks, manually named tracks, locked tracks and tracks with strip/strip-curve modifiers are preserved. Only inactive tool-named tracks containing exclusively this rig's generated results are eligible. Action datablocks are not globally purged or explicitly deleted; Blender's usual unused-data handling applies. This avoids removing Actions shared with current clips or user data.

## Layered pose editing (v0.10.0)

Insert keys normally with Blender's key commands, property-menu insertion or Auto Key. The user's active Action is the upper **Combine** correction layer; the generated NLA strips are the lower **Replace** base. This is Blender's normal active-Action row above NLA tracks, not a second duplicate strip. The basic Timeline continues to show only user keys. No mode switch, per-frame Solo switching or Python pose playback is used.

Blender records the difference between the visible generated pose and the user's edit. Corrections interpolate between native keys while the base continues moving. For example, an arm correction changes that arm over the walking base. Insert neutral correction keys around an edit to limit its duration; Blender's normal interpolation and constant curve extrapolation apply. Deleting a key changes that interpolation rather than selecting a different playback mode. Quaternion keys use all four components, following native Combine behavior.

Existing absolute pose keys are converted once to differences against the current base. Their Action/slot and keyed final poses remain; an untouched **Absolute Keys Backup** Action is retained with a fake user before conversion. The Graph Editor subsequently displays correction values. Pose F-Curve modifiers and sampled curves must be converted to ordinary keys before migration; locked curves must be unlocked. Conversion solves keys on a temporary Action before committing them.

Generation samples the composed final poses at native pose-key frames. Because those poses already contain the correction, new generated base keys exclude that correction before the upper layer is applied again. Explicit authored components are preserved exactly at their existing key frames. This avoids doubling corrections during regeneration or at an inherited, unkeyed start. User correction keys and values remain unchanged after migration; no generated samples are inserted into the user Action. Raw AI output remains in the job result files.

The v0.9 alternating-frame workflow is superseded. Both layers now play together with the addon disabled. Unrelated NLA tracks are not excluded by automatic Solo. Exit native NLA Tweak/Solo modes before generating or inserting correction keys. Moving a motion block does not move independent user keys.

## Linked editing and automatic application (v0.7.0)

Authoring blocks and generated NLA strips are linked by persistent block IDs, not names. Moving a block moves all its matching generated versions. Resizing retimes the linked strips within model duration bounds. Deleting a block removes all its matching NLA strips and empty tracks; the user's active Action and native pose keys are preserved. Moving a block does not move those independent authoring keys. Prompt changes take effect on the next generation.

Native NLA movement, resizing and renaming also update the linked authoring block. Deleting a current playback strip removes its block and matching generated history; deleting only an archived version keeps the current block. Muting an individual native track/strip is retained during timing changes. The block Enabled switch changes generation eligibility and mutes/unmutes linked versions. Existing matching block IDs are adopted on initialization; native timing is used to reconcile save/undo restoration. Unrelated or unmatched historical animation is not deleted.

Generated playback strips share one chronological NLA track. Range edits keep ordinary generated tracks ordered; temporary overlaps must still be resolved before generating. Native strip modifier data is retained on original history strips; copying arbitrary NLA strip-modifier stacks into a new playback snapshot is not supported. Action edits remain shared because snapshots reference the same Actions.

Results are automatically applied through an undoable Blender operator, once per job ID, to the original scene and rig. If a block moves or resizes during generation, the result uses its current timing. Deleted blocks and blocks whose model/prompt changed during generation are skipped. Switching the active scene does not send the motion to the wrong rig. Edit/Tweak Mode or changed FPS temporarily defers application; it resumes automatically when the original conditions are restored. Cancel also clears a pending application. A retry control is shown only if automatic application fails.

Undo/redo and save/reopen retain the block/NLA links. Repeated generations replace the current generated playback track; obsolete plain muted rows are removed after success. Explicitly customized protected tracks can remain linked. Removing the last generated motion restores the user's Action influence. No per-frame Python pose evaluation is introduced.

## Hold and continuation from previous motion (v0.8.0)

Generated strips use **Extrapolation: Hold** and **Blending: Replace**. The last pose remains visible after a block ends and through gaps until another block starts. Live strips are placed chronologically in one **Motion AI Playback** track; obsolete plain generation tracks are removed after successful application. Simply enabling Hold on many simultaneous tracks would let future clips pre-hold over earlier motion. This arrangement uses native NLA behavior, with no per-frame pose handler or influence driver. It also plays with the addon disabled.

Each completed generation creates a new playback track combining its new clips with unaffected current clips, then removes the obsolete plain tool tracks. Existing separate tool result tracks migrate to this layout once. Unrelated NLA tracks are not muted or removed. Matching strips on explicitly protected older tracks continue to follow block timing edits.

When a new job has no native pose key at its first frame, the addon reads the nearest completed preceding strip's endpoint. It adds that pose to the request as a full-body start condition, including Hips translation. This works across Kimodo and MotionBricks. It does not insert a key into the user's Action or create a second pose record. A native pose key at the start takes priority. With no preceding motion, existing first-generation behavior remains: Kimodo can generate freely; MotionBricks requires an authored start.

Kimodo uses the inherited pose as its first full-body constraint. MotionBricks also receives four native NLA samples ending at the new start, at 30 Hz. An adjacent block receives the preceding motion tail; a gap samples the held pose, so an old walking velocity is not incorrectly carried across a long pause. MotionBricks uses the last authored key inside the selection as its destination; block boundaries do not require keys. Text notes do not replace pose targets.

In v0.10, inherited endpoints and their four-pose histories include the current upper correction layer. New bases remove that already-conditioned correction before recomposition, including when no user key exists at the inherited start.

Temporary endpoint sampling isolates the source strip and then restores track/strip mute, solo, influence, frame/subframe, Action/slot, bone modes and unkeyed edits. Generated Actions record their rotation modes for endpoint evaluation. Model limitations still apply: Kimodo's inherited full-body target is converted through its reduced body skeleton, and the inherited start counts toward its pose-target limit.

## Navigation and appearance

The dedicated timeline uses the live Dope Sheet/Timeline background, scrubbing-region background/text, animation playhead color, native widget font and UI scale. It has a separate frame ruler, compact 24-unit motion/keyframe rows, subdued grid subdivisions, scene/preview range curtains, a rounded current-frame tag with a pointer, and a themed horizontal scrollbar. Channels are hidden by default, matching the native Timeline; enable **View > Channels** to show Motion and Keyframes labels in a left column. **View > Seconds** changes time labels. **View > Match Blender Timeline** copies the visible native Timeline start and zoom once, for comparison at the same frame scale; later navigation stays independent.

Version 0.6.2 corrects differences found in the user's comparison screenshot: the grid uses native pixel line width rather than rounded UI scale, minor lines use the native +16 color shade, one-frame grids are drawn once, the scrubbing strip is 23 UI units, and the tag/stalk/triangle use the installed commit's dimensions. GPU scissors include viewport offsets so drawing remains in the correct split editor. These are verified code/geometry changes; visual matching still requires manual screen review.

The header calls the installed Blender `bl_ui.space_time.playback_controls` function in Timeline mode. This preserves Blender's actual auto-key, frame/key jumps, forward/reverse playback, playhead snapping, current frame and Start/End controls. **Add Block** is in the dedicated header; the **Block** menu contains other block commands and generation settings remain in the **Motion AI** sidebar. Previous zoom/generation buttons and instructional canvas text were removed from the header/canvas to match the native arrangement. Native Timeline headers and global node-editor theme settings are unchanged.

Playback redraws the dedicated canvas/header on native frame changes, independently of app polling. Drawing does not sample bone keys or control the rig. The scrollbar thumb pans the view, its ends resize the view, and clicking the track pages horizontally; these are view changes and do not alter animation.

| Control | Action |
|---|---|
| Click / Shift-click block | Select one / toggle additional selection |
| Left-drag empty graph | Box select; Shift adds, Ctrl subtracts |
| B / A / Alt+A / Ctrl+I | Box select / select all / deselect / invert |
| Left-drag frame ruler | Scrub the scene frame |
| MMB / Shift+MMB | Pan horizontally |
| Scrollbar thumb / ends | Pan / resize the visible frame range |
| Wheel / Numpad + and - | Zoom using Blender's native step ratio |
| Ctrl+MMB | Horizontal drag zoom, respecting Dolly/Scale/Continue and inversion preferences |
| Ctrl+wheel / horizontal wheel | Scroll horizontally |
| Trackpad pan / pinch | Pan / zoom |
| Home / Numpad . | Frame all blocks / active block |
| Numpad 0 | Center the current frame |
| Shift+B | Region zoom; right-drag zooms out |
| N | Toggle the sidebar |
| Space | Native Blender playback |

Navigation bindings live in the View2D addon keymap and poll only in this dedicated editor. Ordinary node editors and native animation editors retain their controls. The addon does not add a button to the native Timeline. The editor uses Blender's custom NodeTree extension point; Blender's source code is unchanged. The editor-type selector may list it under General rather than Animation.

The active block has one **Model** selector. Kimodo and ARDY expose **Text Encoder**, **Prompt** and **Path Curve**. Only Kimodo exposes Transition Overlap. MotionBricks exposes **Notes**, which are labels only and are not sent to a text model. Seed, model-specific steps, post-processing and guidance are grouped under the collapsed **Advanced** section.

## Connected generation

Only the explicitly selected, touching blocks of one model are submitted. Selection does not change each model's native transition algorithm described below.

**Kimodo:** ordered block prompts and durations are passed to the official `multi_prompt=True` path. It generates segments with overlapping transition context and post-processing, rather than concatenating unrelated clips. Pose targets use sequence-relative frame indices. A worker-local compatibility guard removes empty cropped constraint sets before conditioning; pinned upstream source files are unchanged. This fixes multi-block jobs in which a segment contains no authored pose targets.

**MotionBricks:** a single transition plan passes through all native pose keys across the connected blocks. No keys are required at block boundaries. Every additional native pose key is a waypoint, and the last is the final stop target at its authored time. The first context contains four preceding-motion samples when the start is inherited, or authoring-Action samples at the first pose key otherwise. Each subsequent transition receives the last four resampled output poses actually used by Blender. Unused leading/trailing block time holds the first/last pose. It does not restart from a repeated static pose at every block boundary.

**ARDY:** autoregressive 60-frame windows advance until each block's exact output length is reached, retaining up to 240 frames of motion history. Block prompts change at their boundaries; non-token-aligned boundaries are supported through internal history padding and output trimming. Native pose/path constraints and prior-model canonical SOMA history use the same addon coordinate space. See [ARDY details](ARDY_BLOCKS.md).

Interior targets carry four native Action samples at 30 Hz, starting at the target pose. This communicates authored velocity/acceleration into the next transition. The final one-pose target requests a stop. Output is resampled to the authored timing and shared waypoint frames are emitted once. MotionBricks does not accept text prompts.

These methods support continuity, but do not guarantee perceptually natural motion for conflicting poses, abrupt direction changes or unsuitable timing. Each backend request uses one model. A mixed selection is generated as successive model runs, carrying composed endpoints across model changes rather than evaluating models jointly. One Generate Motion operation accepts up to 32 contiguous blocks; only ARDY-only selections bypass the 60-second operation cap.

Official references: [Kimodo model API](https://research.nvidia.com/labs/sil/projects/kimodo/docs/api_reference/model.html), [MotionBricks chaining](https://github.com/NVlabs/motionbricks/blob/main/docs/inbetweener.md#playback-and-chained-generation).

## Duration bounds

| Model | Per-block length | At 30 FPS | At 24 FPS |
|---|---|---|---|
| Kimodo | 2-10 seconds | 60-300 frames | 48-240 frames |
| MotionBricks | 18-58 samples at 30 Hz | 18-58 frames | 15-46 frames |
| ARDY | At least one 30 Hz output frame; no model maximum | 1 frame or longer | 1 frame or longer |

Both edge dragging and numeric edits clamp to these limits, converted to scene FPS. Changing FPS can invalidate old authoring ranges; adjust them before generating. The companion app validates the same `model_limits.json`. Linked native strips follow their authoring block duration; unlinked model-tagged strips retain native duration guards. Unrelated strips are untouched.

Starts are inclusive and ends exclusive: `[1, 31)` contains frames 1 through 30. MotionBricks keys may lie anywhere within selected blocks; they do not need to align with block boundaries. Kimodo permits at most 19 full-body pose targets per job, including an inherited start. Use whole-frame native pose keys.

MotionBricks predicts its own duration; the adapter resamples each transition to the requested timing. This can change speed and contact quality. Its native 6-16 tokens contain four poses each, with three boundary frames removed at each end, giving 18-58 output frames. Earlier unrestricted 0.5-10 second adapter retiming is no longer the block-size policy.

## Animation ownership and persistence

One 77-bone SOMA armature holds the user's active correction Action and generated native NLA playback track. AI runs in the separate companion app using embedded Python. Each completed generation is applied automatically to a new chronological playback track, combining new Actions/strips with unaffected current clips. Obsolete plain tool tracks are then removed. The active user Action and slot remain assigned; absolute keys are converted once with a backup, then user key data is retained during generation. No new armature is created.

Blender evaluates generated keys through native NLA. There is no Python pose playback, per-frame cache decoding or generated constraint rig. Saved generated motion plays with the addon disabled. Generation temporarily enables the user Action over NLA to sample keyed poses, restoring the Action, frame/subframe, influence and displayed motion afterwards. In the legacy authoring-only helper, NLA is bypassed instead.

Layered editing keeps active-Action influence at one with Combine blending. Both layers evaluate continuously. Old tracks are muted during staging for rollback, then eligible inactive rows are removed only after success. Native strip mute choices are retained. Non-pose Action channels, such as object placement, stay on the user Action rather than being duplicated in generated bases. Legacy base copies are cleaned while original Actions are retained. Native NLA Tweak Mode is available for editing results; exit Tweak Mode before generating.

Every frame with an eligible SOMA bone-transform key produces a pose target. Full Body is the default even if only one bone was keyed; v0.22.0 lets the user annotate that frame as LH/RH/LF/RF/R2 instead for Kimodo/ARDY. The composed pose supplies the selected target's position/orientation. Object keys, custom-property keys, other slots and muted curves do not create targets. Removing a native bone key automatically removes that pose target and its annotation. No Capture Pose/Delete Pose interface is used.

Prompts, authoring blocks, native keys, generated Actions and NLA arrangement are stored in the `.blend`. Empty v0.5 native request strips are imported into dedicated authoring blocks once and removed; generated and user-keyed Actions are retained. If no authoring blocks exist, a selected/latest generated track can seed them. Older cache/constraint previews migrate once to native NLA. Legacy result armatures are consolidated only when safe; customized or referenced rigs are retained.

## FPS endpoint correction (2026-11-07)

A reported BF16 Kimodo job used scene FPS 60, range `[1, 121)` and pose keys at 1 and 120. The generated 30 Hz output contains samples 0 through 59, but rounding the final key previously produced sample index 60. Generation ran, then result validation raised an IndexError; the endpoint constraint could also be cropped out of generation.

The protocol and worker now share a bounded nearest-sample mapping. Frame 120 maps to sample 59 for both conditioning and error measurement. Native keys that collapse to the same 30 Hz sample are rejected before generation. Frame sampling is still limited by the model's 30 Hz rate.

Workers open their own diagnostic stream because inherited Python stderr can be absent when launched through a Windows GUI. Exceptions also persist to the job's `error.json`. The service reports structured worker errors or the native Windows exit code instead of only a generic failure. Since v0.11 workers are resident, restart the app after worker/service updates so the new code is loaded.

The exact failing request was reproduced before the fix and replayed successfully afterward using the existing BF16 encoder. `fps_endpoint_regression.json` covers 13 scene frame rates and diagnostic fallbacks. `blender_fps_endpoint_result.json` verifies the actual repaired output at scene frames 1, 61, 119 and 120, one SOMA armature and unchanged user Action/slot/keys; maximum rotation-matrix difference was about 1.8e-6. `fixed_60fps_endpoint.blend` is the isolated replay fixture. These checks do not certify general motion quality.

## Coordinates and scope

SOMA uses Y-up meters, mapped to Blender by `(x, y, z) -> (x, -z, y)`. Creation-time unit scale and rest matrices are preserved. Edited rest skeletons, non-root translation and bone scaling are unsupported. Quaternion and Euler user rotation modes are retained. Automatic application requires the original scene, input rig and scene FPS.

New SOMA armatures default to **Octahedral** display with **Names** off, **Shapes** on and **Bone Colors** on (v0.14.2). Existing armature display choices are preserved.

Kimodo and ARDY generate a 30-joint body representation expanded to 77 joints; fine finger targets are not independently authored. ARDY is integrated through finite timeline blocks, not an open-ended Start/Stop live session. Arbitrary-character retargeting and custom IK controllers are not part of this addon. No ARP code/assets or other addons are modified.

## Validation (through 2026-11-08)

- `pose_constraint_ui.json` (v0.22.0): current-key sidebar, right-click hit/menu, native GPU labels, annotation moves/deletion/reinsertion, default FB, mixed typed requests, MotionBricks rejection, save/reopen and Undo/Redo.
- `pose_constraint_generation.json` (v0.22.0): real Kimodo/ARDY mixed constraint types, hand/foot target position/orientation, curve combination and native NLA/source-key preservation.
- `ardy_blocks.json` (v0.21.0): model selection, one-frame minimum/no duration maximum, requests beyond 60 seconds, 24/60/120 FPS bounds, prompt/curve/precision/step controls, pose targets and save/reopen.
- `ardy_generation.json` (v0.21.0): real non-token-aligned prompt sequence with native pose keys/shared curve, exact output length, one-frame continuation and a 1801-frame bounded-history rollout with resident model/encoder reuse and native NLA application.
- `ardy_mixed.json` (v0.21.0): one-command Kimodo -> ARDY -> MotionBricks -> ARDY jobs, inherited boundaries, encoder reuse and preserved native source keys/Action/slot and one SOMA/playback track.
- `transition_overlap.json` (v0.19.0): Kimodo-only sidebar/popup input, legacy default 5, per-block persistence, invalid/oversized values and stale pending/completed request detection.
- `previous_kimodo_context.json` (v0.20.0): native preceding-tail sampling and state restoration, explicit user Start key, minimum overlap support, gaps/oversize handling and payload validation.
- `previous_kimodo_generation.json` (v0.20.0): actual single-block history overlap including user corrections, raw/minimum/full-tail contexts, preserved predecessor Actions/source keys and an externally seeded multi-block sequence.
- `transition_generation.json` (updated v0.20.0): actual 0/7/13-frame model context windows with and without postprocessing, single-block overlap from its existing predecessor, native NLA application and saved pre-feature request replay.
- `shared_curve.json` (v0.18.1): scene-wide shared route grouping, unequal durations, stable partial regeneration, gaps/different objects/disabled neighbors, unselected-neighbor stale detection, 24/60/fractional FPS and save/reopen.
- `shared_curve_generation.json` (v0.18.1): real two-block shared-route sequence and second-block-only regeneration, inherited endpoint, unchanged first clip/source keys, one SOMA and one native playback track.
- `curve_paths.json` (v0.18.0): native Bezier/Poly/NURBS centerline sampling, scene/rig transforms, centimeter units, bevel/extrusion isolation, popup selection/clear, invalid/stale path rejection and save/reopen.
- `curve_generation.json` (v0.18.0): real two-curve Kimodo sequence, native NLA evaluation including prior root key frames, no-curve continuation and a new inherited curve, one SOMA/track and preserved source keys.
- `curve_unkeyed.json` (v0.18.0): actual curve-only generation without pose keys, scene-offset path, initial tangent heading, 30 Hz to 60 FPS interpolation and automatic connection.
- `motion_progress.json` (v0.17.0): atomic completed-work snapshots, monotonic percentages and HTTP serialization.
- `live_motion_progress.json` (v0.17.0): real Kimodo two-block/120-step job and MotionBricks two-transition job, live intermediate HTTP percentages and exact completed/total counters.
- `progress_and_block_ui.json` (v0.17.0): native progress-widget API, mixed-run percentage aggregation and 100% only after final application; no editable name in popup/sidebar and unchanged automatic name/UID after prompt edits.

- `selection_alpha.json` (v0.14.1): actual GPU framebuffer reads confirm 5% white-over-background compositing after BLF text rendering; grid lines remain visible and the fill is not opaque white. Maximum RGB error is below 2/255, allowing 8-bit quantization.
- `unified_motion_timeline.json` (v0.16.0): real one-row hit testing and append behavior, actual GPU pixels for native selected/unselected key colors, native key deletion reflected in the display, sidebar timing removal and mixed queue cancel/failure/edit handling.
- `mixed_generation.json` (v0.16.0): real Kimodo -> MotionBricks -> Kimodo sequence from one command, both inherited composed endpoints (maximum matrix/root component difference below 3e-6 in this fixture), MotionBricks history and non-boundary final key, unchanged user Action/slot/keys and selection, one SOMA/track and an untouched unselected block.
- `block_selection.json` (updated v0.16.0): real Scene RNA with synthetic modal events for click/toggle/box/add/subtract/cancel, explicit-only generation, touching mixed-model acceptance and gapped/disabled rejection, ruler scrub, group/NLA drag, multi-delete, native undo/redo, one command surface and save/reopen. No user GUI was automated; visual/mouse acceptance remains manual.
- `selected_generation_kimodo.json` and `selected_generation_motionbricks.json`: real single-button GPU jobs generate exactly two selected blocks, then exactly one selected completed block, while preserving the unselected neighbor, prior Action, one playback track and resident motion-model reuse.
- `nla_cleanup.json` (v0.12.0): append/regenerate keeps one current generated track, shared Actions and user keys remain, native undo/redo restores prior results, protected tracks survive, and old saved plain history rows are removed on load without changing current playback.
- `resident_motion.json` (v0.11.0): real GPU reuse, retained CUDA allocations, one model load per process, equivalent seeded output, engine and encoder-profile switching, full Release GPU and clean reload; cold/warm timings recorded.
- `resident_controls.json`: HTTP generation, seeded-rotation consistency, structured worker failures, cancellation, recovery, full release and residency status UI contract.
- `unified_keying.json` (v0.9.0): real native LocRot insertion, channel insertion, Pose Mode Auto Key, keyed-frame priority, key deletion/movement, combined-pose model input, native undo/redo, save/reopen and addon-disabled generated playback. A 120-frame evaluation took approximately 0.04 seconds in this isolated fixture; this is not a general performance guarantee.
- `layered_corrections.json` (v0.10.0): native partial-arm correction interpolation, other local rotations retained, regeneration without double corrections or changed user key values, strongly corrected inherited start, Auto Key, native undo/redo, v0.9 migration with backup, save/reopen and addon-disabled layered playback.
- `layered_modes.json`: Euler and axis-angle keys, root and object-channel composition, repeat-generation name collisions and injected-failure rollback to the previous native tracks and user keys.
- `unified_motionbricks.json`: real MotionBricks generation from native correction keys, including four prior composed poses, automatic HOLD clips, user Action/slot/keyed poses and one SOMA. Endpoint agreement is numerical and fixture-specific, not a general motion quality guarantee.
- `live_auto_apply.json`: two real BF16 Kimodo jobs with automatic native layering, inherited endpoint conditioning and linked block move/delete.
- `hold_continuity.json` (v0.8.0): full 77-bone pose hold, gaps, explicit-key priority, previous-tail sampling, pending-only sequences, source state preservation, reverse seeking/reordering, legacy-track migration and addon-disabled native playback.
- `hold_workers.json`: real MotionBricks (58 frames) and Kimodo (60 frames) requests seeded from a previous native endpoint. Maximum start root-coordinate error was below 3e-10 m; maximum local rotation-matrix difference was about 2.4e-6 for this fixture. This is endpoint/functional verification, not a general motion-quality guarantee.

- `linked_motion_blocks.json` (v0.7.0): timer-driven automatic application, duplicate-result suppression, all-version move/resize/delete, native edits, track mute/order preservation, delayed results after block changes, original-scene routing, FPS deferral and save/reopen.
- `linked_undo.json`: native Blender global undo/redo for linked deletion and native-only move/delete snapshots.
- `live_auto_apply.json`: real BF16 generation at scene FPS 60 through the running companion HTTP app, automatic NLA application without an Apply click, then linked move/delete and source Action/slot preservation. The user's GUI was not automated.

- `block_timeline.json`: connected/gapped/overlapping blocks, bounds, per-block sidebar, drag/cancel/delete, native keys and pose windows, request migration, one SOMA, source Action preservation, save/reopen and addon-disabled NLA replay.
- `block_navigation.json`: native zoom step read from installed Blender RNA; 17 View2D bindings compared with installed defaults; synthetic modal pan/zoom, mouse preferences and region zoom.
- `blocks_redraw.json`: 60 frame changes and one subframe change each trigger dedicated canvas/header redraw without polling or bone writes.
- `native_timeline_style.json` (v0.6.2): header widget calls compared directly with installed native Timeline controls; live theme updates, font/scale geometry, FPS grid and scrollbar pan/resize/cancel checked. The native presentation references [Blender time scrubbing UI](https://github.com/blender/blender/blob/e13b728c6880/source/blender/editors/animation/time_scrub_ui.cc) and [animation drawing](https://github.com/blender/blender/blob/e13b728c6880/source/blender/editors/animation/anim_draw.cc); execution checks use the installed Blender 5.2.3 Python UI.
- `blocks_draw.json`: real Blender theme properties and canvas code exercised with mocked GPU/font calls. This is API/state verification, not a rendered UI review.
- `blocks_workers.json`: real two-block GPU jobs: MotionBricks 60 frames, Kimodo 120 frames with different prompts. Context handoff and target-window metadata checked. Kimodo uses NF4/10 denoising steps for this functional test; it is not a quality comparison.
- `blocks_live_results.json`: fresh outputs replayed through native NLA, including shared block boundaries; maximum rotation-matrix difference about 2.1e-6. User Action/slot and one armature retained.

Reports and saved fixtures are under `results/blender_bridge`. Earlier NLA-authoring and cache-preview reports document historical workflows. Interactive appearance, physical mouse behavior and perceptual motion quality require user review. No user GUI was automated for these checks.
