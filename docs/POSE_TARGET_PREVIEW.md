# Pose Target Preview

Version 0.32.0 adds an object-free 3D viewport overlay for the constraints passed to **Generate Motion**. It uses only the selected motion blocks and the same request builder as generation. The companion app does not need to be running.

Enable **Show Pose Targets** in the Motion AI sidebar. The viewport's **Show Overlays** must also be enabled and the input SOMA rig must be visible. Under **Advanced > Pose Target Display**, use **Line Width** and **Line Opacity** to adjust the preview lines. Point opacity and radius have separate settings. The same section controls in-front drawing, rotation axes and frame labels. This display creates no armature, mesh, Action, keyframe or collection and is not included in renders or exports.

## Display

| Target | Display |
| --- | --- |
| FB — Full Body | Blue stick skeleton with 1.5 px lines (scaled for UI density) and 35% opacity by default |
| LH — Left Hand | Cyan wrist and middle-finger endpoint spheres |
| RH — Right Hand | Orange wrist and middle-finger endpoint spheres |
| LF — Left Foot | Green ankle and toe-base spheres |
| RF — Right Foot | Pink ankle and toe-base spheres |
| R2 / R2H | Yellow ground-plane root sphere; H adds a heading line |
| R3 / R3H | Yellow sphere at the constrained root height; H adds a heading line |
| Hips | Purple pelvis sphere for ARDY's implicit pelvis target in hand/foot constraints |

Smaller yellow spheres show auxiliary root position/height goals carried by hand/foot constraints. If ARDY also has a curve, its auxiliary curve-root goal is shown separately from the purple pelvis point. Optional wrist/ankle rotation axes show the orientation component of the target. Multiple constraint types on the same native key produce multiple colored targets. Labels include the source frame and type; **Previous** identifies an inherited endpoint from an existing generated clip.

## What is previewed

Targets come from the composed visible pose (native generated NLA plus user corrections) at authored pose keys. Generated NLA keys do not become extra pose constraints. Moving/deleting native user keys, changing their constraint types, selecting different blocks, changing a curve or applying a new result refreshes the overlay. An invalid selection/request clears stale targets and displays the request error below the toggle.

Kimodo and ARDY use their native reduced 30-joint skeleton. The display therefore applies their actual 77-to-30 local-rotation selection; it does not pretend that omitted finger rotations are model constraints. MotionBricks reads the canonical 77-joint pose and displays its body skeleton. The display uses the same root-path projection and 30 Hz frame mapping as the workers. A root-only 2D target is drawn on the rig's ground plane because height is unconstrained; enabling height moves it to the keyed height. World placement, rig scale and scene units are respected.

Full Body overlays omit End and Eye branches to match the cleaner rig display. This filters drawing only: FK and model input retain every required joint. Hand/foot goal spheres still show the actual native position targets.

For adjacent mixed-model selections, later groups initially preview the constraints available in the current scene. Generation may replace their inherited start with the newly generated predecessor; the overlay refreshes after results apply. No preview can predict that future generated pose. MotionBricks' four-frame context/target windows and autoregressive history are still sent normally; this overlay displays the principal keyed poses, not every history sample or every dense curve sample.

The overlay shows model input goals, not a guarantee that generated motion will meet them. Soft root-height and other conditioning retain their existing model limitations. This feature does not change inference, postprocessing, user correction layers or NLA playback.

## Refresh and validation

Geometry is cached. Changes are debounced; sampling and rebuilds pause during playback and dedicated timeline key drags. The existing cached targets can remain visible during playback. The sampler restores frame/subframe, object and pose transforms, active Action/slot and native keys.

Live editing fix: rebuilds also pause during native modal interactions (including bone transforms) and armature Edit Mode. Pose-target sampling now restores unkeyed pose edits **after** the authoring evaluation context exits. Previously that context re-evaluated the frame after restoring channels, replacing an unkeyed edit with its animated value. A preview-wide guard also preserves live transforms on other scene armatures and animated objects, since sampling another frame evaluates the whole scene. This restoration runs on failed requests as well. Saved keys remain the model targets even when the user is currently holding a different unkeyed pose.

Actual Blender 5.2.3 background tests cover selected scope, combined targets, delayed curves, centimeter/world transforms, key type changes/deletion, save/reopen, unchanged-input cache reuse, inherited NLA endpoints and MotionBricks targets. Native GPU offscreen drawing verifies the skeleton and sphere renderer. No additional scene objects or authoring keys are created. CPU comparisons against the installed Kimodo/ARDY skeleton and constraint classes measured a maximum position difference below 0.000001 m, including reduced finger handling and ARDY's pelvis coupling. These checks do not replace user review of the interactive viewport.

Reports: `results/blender_bridge/pose_target_preview*.json`, `pose_preview_scene.json`, `pose_preview_native_fk_kimodo.json`, `pose_preview_native_fk_ardy.json`. Restart Blender after updating; the companion app needs no restart.

`pose_preview_editing.json` and `pose_preview_editing_installed.json` reproduce the unkeyed-edit regression and verify arm rotation/hips translation at keyed and unkeyed subframes, direct native target sampling, generated NLA with a curve, two edited characters, another animated object and a failed curve request. The reproduced pose difference becomes zero after the fix. Native interactive mouse dragging remains subject to user viewport review; the background tests exercise the real animation evaluation and refresh paths.
