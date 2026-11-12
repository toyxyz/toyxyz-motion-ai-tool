# SOMA FK and IK controls

Select an actor and click **Add Control Rig** below the **SOMA Rigs** list in the **Motion AI** sidebar. The button is always visible and becomes available when you select a visible actor that has no controls yet. After setup, the collapsed **Control Rig** panel contains separate **FK** and **IK** switches for each arm and leg.

The panel lists **Left Arm**, **Right Arm**, **Left Leg**, and **Right Leg** in that order. All four limbs start in FK when you add controls. Saved controllers keep their authored modes.

- In **FK**, rotate the limb controls with Blender's Rotate tool or `R`.
- In **IK**, move or rotate the hand or foot box. Move its pole with Blender's Move tool or `G` to guide the elbow or knee. The pole is parented to the hand or foot target.
- The smaller body ring controls the pelvis. The ground circle is the actor master.
- The left and right clavicle boxes follow the clavicle bones from the chest to the upper-arm joints. Existing stock clavicle rings update when the add-on refreshes the scene.
- Finger bones are visible in the **SOMA Fingers** collection on a plain SOMA rig. After **Add Control Rig**, use the color-coded FK boxes in **Controls · Fingers**. Select a box in Pose Mode, rotate with `R`, and insert a Rotation key. Finger controls follow the solved wrist in both arm modes. You can show or hide the active finger collection in the armature's **Bone Collections**.
- **Show Matched Controls** displays the inactive limb guides in gray. The active controls are selectable. The gray guides are read-only and follow the evaluated limb.

Whole-rig rotation around a shared pivot keeps finger and toe articulation relative to the wrists and ankles. Their controllers sit below the master in the native bone hierarchy. Older stock rigs update when opened in a view layer where the actor is visible and editable. Existing Actions and FK/IK settings carry over.

Switching copies the current pose into the destination controls and inserts a stepped FK/IK key at the playhead. FK and IK have separate transform channels. In FK, the dormant IK target evaluates at the FK wrist or ankle. In IK, the read-only FK guides follow the evaluated joint transforms. The rig uses native Blender constraints and simple drivers for following and playback. Moving or deleting a pose key in the Motion Timeline also moves or deletes its associated mode key.

The original 77 SOMA bones drive the body mesh and supply model pose targets. Existing native Actions are copied for remapping when a rig is set up. Generated Actions carry matching FK and IK channels so either mode can play generated motion. The upper user Action continues to combine with generated NLA. The limb lengths are fixed, so reachable targets give the closest match when switching.

Finger animation is authored in the user Action. Newly generated NLA strips animate the wrist and leave the finger channels to that Action. Frames with finger keys alone remain editable in the Motion Timeline and have no pose constraint label. When a frame also has a body or wrist key, the model uses the body pose with neutral fingers. Existing rigs receive the finger display update on open. The stock box placement follows the per-joint control layout in [Auto-Rig Pro's finger controls](https://www.lucky3d.fr/auto-rig-pro/doc/auto_rig.html#fingers-shapes).

When a generated elbow or knee is nearly straight, baking rotates the SOMA rest-pose direction with the upper limb. Knees use the forward axis and elbows use the backward axis. As the joint flexes, the segment rotations gradually guide the pole toward the generated pose. Sampling uses the same calculation on either side of a block boundary. Regenerate a previously baked block to update its pole keys.

## Validation

Blender 5.2.3 background checks cover active FK rotations and IK target movement, matching guides, four-limb mode switching, finger and toe following, native key targets, regeneration, Clear Motion, existing Action migration, and replay after reopening. Replay of recorded Kimodo, MotionBricks and ARDY clips checks both modes. The tests exercise controller transforms programmatically. Mouse and gizmo interaction can be reviewed in the viewport.

In the near-straight regression, elbow and knee bends alternate across the limb axis beyond the previous 3 mm cutoff. The new maximum pole turn is 1.30° across 59 samples, both in one result and in two separately applied results. Reverse seeking returns the same directions. Recorded Kimodo, MotionBricks, and ARDY fixtures have a maximum wrist or ankle deviation below 0.1 mm between FK and IK. The largest difference across all joint heads in those fixtures is 7.1 mm.
