# SOMA preview mesh (v0.28.0)

## Controls

- **Create SOMA Rig + Mesh** creates the existing 77-joint SOMA input rig and adds its body mesh. In an older scene, select the original **SOMA Input Rig** and click the same button to add the mesh. It reuses that armature and preserves its current pose, Action/slot, pose keys and generated NLA.
- **Show SOMA Mesh** toggles the preview body in the viewport and renders. Bones remain available, with the existing Octahedral/in-front display.
- The body is a child named `toyxyz_motion_ai_tool_SOMA_Mesh` in the rig's collection, with a neutral preview material and smooth shading. It is not selectable by default, so posing selects the rig rather than the body. Its Outliner selection restriction can be changed normally.
- Repeated creation reuses the current preview. If only the visible mesh was deleted, creation rebuilds it while reusing the matching internal influence cloud. Removing the hidden skin helper while retaining the visible mesh produces an explicit repair instruction.

Restart Blender to load the addon update. The companion app does not need to run or restart to add, pose or play the mesh.

## Asset and binding

The asset is the official `skin_standard.npz` distributed with the companion's Kimodo SOMA assets, with the identical ARDY location accepted as a fallback. It contains 18,056 vertices, 36,108 triangles, 77 joint names, bind matrices and skin weights. It is read locally with Blender's bundled NumPy and `allow_pickle=False`. No AI package, extra body-model download or companion process is needed. A missing asset leaves the rig usable and reports which app-folder setting to check. Existing saved previews need no asset file for playback.

The skin uses the same fixed body proportions as motion generation. This feature does not add body-shape editing or retargeting. Source asset geometry and weights stay in the companion installation; they are not duplicated into the addon package. Blender embeds the created geometry, weights and native deformation setup in the saved `.blend`.

The reference skin implementation is [NVIDIA Kimodo SOMASkin](https://github.com/nv-tlabs/kimodo/blob/main/kimodo/viz/soma_skin.py). Its bind matrices differ from the editable Blender rig's rest matrices. Simply baking one rest-pose mesh and assigning ordinary blended armature weights can introduce bind-frame errors when joints rotate. The preview therefore represents each nonzero skin influence as a rigidly weighted point on the existing armature. A native Geometry Nodes group accumulates the weighted positions back onto the original mesh topology. This reproduces the official linear blend skinning equation without changing the model skeleton.

`SOMA Skin Influences` is an internal hidden point-mesh child, not another armature. It has one Armature modifier referencing the input rig. The visible body has the native `SOMA Preview Skin` Geometry Nodes modifier. No Python frame handler, motion cache, dependency on an AI process, or extra animation Action is introduced. The setup works with user keys, generated NLA, ordinary rig object transforms and scene-unit conversion. It stays functional when the addon is disabled.

## Validation

Separate factory/background Blender 5.2.3 instances were used; the user's GUI was not controlled.

- `results/blender_bridge/soma_preview_mesh.json`: actual evaluated vertices compared against an independent NumPy evaluation of the official bind matrices/weights. Cases include neutral, arm/elbow/knee/root changes, translated root, saved real Kimodo/MotionBricks/ARDY NLA results and armature object translation/rotation/scale. The tested maximum errors were below 0.01 mm. Repeated creation, existing-rig upgrade, visibility, Undo/Redo and source key/Action/slot preservation are covered.
- `soma_preview_mesh_centimeters.json`: the same checks with scene length scale 0.01, comparing deformation in physical meters.
- `soma_preview_mesh_installed.json`: installed addon/source equality plus the preview checks.
- The saved preview is reopened and played after disabling the addon. `soma_preview_mesh.png` is a background Workbench render of that saved scene without an AI model or addon startup.
- Existing `timeline_pose_edit.json` and `layered_corrections.json` regression checks pass with the preview mesh attached.

The initial fixture evaluated frame changes, including mesh deformation and vertex readback, in roughly 3 ms per frame on this machine. This is a local fixture measurement, not an interactive frame-rate guarantee. Numerical binding and native playback checks do not establish model motion quality or manual UI acceptance.
