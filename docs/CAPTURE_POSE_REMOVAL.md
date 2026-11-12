# Capture Pose removal

Date: 2026-11-08. Version: 0.36.0.

The user withdrew image-based pose capture: RTMW-to-SOMA pose quality was not
suitable for the intended workflow, and Fast SAM 3D Body startup was too slow.
Capture Pose is no longer an addon or companion feature.

## Removed

- Capture Pose sidebar button, capture status, image window, image inference,
  Apply Pose operators, timer callbacks and capture-session cleanup hooks.
- Companion `image_pose_capture` capability, `/capture/...` GET/POST routes,
  `CaptureManager` and image-job concurrency checks.
- Active image inference/conversion modules, downloads, requirements and test
  tools. Their small source snapshots remain under
  `development/removed_image_capture/v0.35.0/` as withdrawn historical code.
- Private embedded-Python package folders `fast_sam_3d_body` and `rtmw3d`.
- Model folders `models/fast_sam_3d_body` and `models/rtmw3d`.
- Third-party checkouts `engines/fast_sam_3d_body`, `engines/dinov3` and
  `engines/rtmw3d`. They had no local source modifications before removal.

The installed addon was updated through its deployment receipt. The obsolete
`capture_pose.py` and its cached bytecode were removed from the Blender addon
directory. Other addons were not changed.

## Retained

Existing native user pose keys, Full Body annotations, corrections, generated
NLA strips, blocks, rigs and SOMA preview meshes remain editable. Captured poses
were native Blender keys, so they do not require the withdrawn image model or
Python module for playback. No user `.blend` file was edited or deleted.

Kimodo, ARDY, MotionBricks, their models, the shared text encoders, BF16/INT8/NF4
options and common Python packages remain installed. The original runtime lock,
environment manifest and local split runtime archives did not include the two
experimental private package folders, so they require no rebuild for removal.

Historical measurements, review `.blend` files and images remain under
`results/fast_sam_3d_body/` and `results/rtmw3d/`. Their documentation now clearly
identifies the feature as withdrawn; old reproduction commands require restoring
the former experimental environment.

The general idle-companion upgrade helper was separated into
`runtime/ensure_companion_service.py`. Start updates a verified idle service
that still advertises image capture, while busy jobs and foreign installations
are protected. Blender-owned process lifetime support remains active.

## Space reclaimed

| Removed assets | Bytes | Approximate size |
|---|---:|---:|
| Fast SAM private Python packages | 167,099,889 | 159.36 MiB |
| RTMW private Python packages | 422,647,750 | 403.07 MiB |
| Both private Python folders | 589,747,639 | 562.43 MiB |
| Both model folders | 3,174,572,819 | 2.96 GiB |
| Three third-party checkouts | 126,146,489 | 120.30 MiB |
| Total named assets removed | 3,890,466,947 | 3.62 GiB |

These are logical file sizes, not a measurement of physical disk allocation.
Common package files were not uninstalled individually or modified. Shared
download caches were retained because their contents can serve other models.

## Validation

- Installed-addon registration, sidebar, main-thread timer and file-load paths
  run without the image module/operators.
- An existing Capture Pose test scene loads with native keys, FB metadata and
  NLA intact. Saving to a new file and reopening preserves exact key/strip data
  and the evaluated pose; maximum rotation-matrix entry difference is zero.
  The original file hash is unchanged.
- A fresh companion on an isolated port reports all three motion engines, omits
  image capture and returns HTTP 404 for former capture routes. Release GPU and
  graceful shutdown pass without image packages.
- Installed Start/reconnect/Stop checks pass, including actual process startup,
  reuse of the same instance and shutdown. Controlled upgrade checks protect
  busy jobs and foreign installations and reject changed service identity.
- Installed Clear Motion regression passes, including Undo/Redo, save/reopen,
  per-rig isolation and preservation of native user animation.
- Full original embedded-runtime verification passes for all **45,501 files**.
- Kimodo, ARDY and MotionBricks environment checks pass: required modules load,
  CUDA executes a small tensor operation, and no external development-runtime
  DLL is used. This is an environment check, not a new motion-quality evaluation.

Evidence is under `results/capture_pose_removal/`: asset receipts, source hashes,
`blender_installed.json`, `service.json`, `upgrade_tests.json`, integrity log and
per-engine doctor logs. Start/Stop and Clear Motion reports remain in
`results/blender_bridge/`. Tests used background Blender, with no computer-use
automation or interaction with a user scene.

The old idle companion was identified by its exact executable/script/port and
instance, then gracefully stopped. Restart Blender to load addon 0.36.0 and use
**Start** to run the updated companion.
