# Blender-owned companion lifetime

Version 0.35.0 makes the companion and its model processes end with Blender,
including abnormal Blender termination. Restart Blender after installing this
update, then click **Start** once. An idle companion running older code is
upgraded automatically. Generation is never interrupted to perform that upgrade.

## Behavior

- Closing the last Blender that owns the companion terminates that companion,
  its resident motion/text model processes.
  GPU allocations belonging to those processes are released by Windows/driver
  process teardown.
- The same cleanup happens if Blender crashes or is forcibly terminated. It does
  not depend on a Python exit handler, a Blender timer, HTTP availability or a
  heartbeat timeout.
- If two Blender processes use the same companion, it remains available after
  the first closes. The last owning Blender's exit triggers cleanup.
- Connecting to a compatible companion that was already running also establishes
  ownership. Merely losing a network connection or loading another .blend file
  does not end the Blender process lifetime.
- Explicit **Stop** still stops the companion immediately. **Release GPU** keeps
  the companion alive and unloads/cancels its models as before.
- This feature owns this app's processes. It does not empty another application's
  GPU memory or terminate another installation's processes.

## Windows implementation

The addon holds a named Windows Job Object with `KILL_ON_JOB_CLOSE`. Names contain
an installation-path hash and a random instance identity. Each connected Blender
holds a handle to the same object. The companion joins that job and immediately
closes its borrowed handle; it never keeps its own lifetime alive.

Blender prepares the job before Start. New startup helpers and
companions join it before loading models. Reconnect checks the installation root,
executable path, PID and exact Windows process creation time before binding an
existing companion. PID reuse or mismatched identity is rejected.

The existing companion-owned inner job covers newly spawned workers. A verified
same-installation encoder that predates the companion is also adopted into that
inner job. This prevents an adopted encoder from being left in VRAM if either
Blender or the companion itself exits abnormally. Other installations' encoders
are not adopted.

The only persistent lifetime handles are in owning Blender processes. Closing the
last handle is enforced by Windows even if Blender's Python cleanup never runs.
Normal addon unregister also closes its handles. Cleanup terminates model workers;
it does not wait for an in-progress inference to finish.

Files:

- `addons/toyxyz_motion_ai_tool/lifetime.py`: stdlib-only native job handles and
  process identity validation; no ML imports.
- `runtime/blender_owner.py`: loads the same native job helper without importing
  the Blender addon or bpy.
- `runtime/entry.py`, `runtime/ensure_capture_service.py`: early startup binding.
- `runtime/process_owner.py`: inner worker job and verified encoder adoption.
- Addon Start, Capture startup and client health handshake retain owner handles.

## Validation

`build_tools/test_blender_lifetime.py` creates disposable factory-startup Blender
processes. It never closes the user's running Blender or app. Reports are under
`results/blender_lifetime/`, with an index in `latest.json`.

Verified cases:

1. Normal Blender exit kills the companion, child workers and adopted process.
2. Forced Blender termination performs the same cleanup without exit callbacks.
3. Forced companion termination kills its children/adopted process while Blender
   remains alive.
4. Two independent Blender owners preserve the app after the first exit and
   terminate it after the last exit.
5. A Blender that attaches after the companion and workers started also owns
   their complete shutdown.
6. The actual addon Start/HTTP connection path shuts down its real companion on
   forced Blender termination.

Normal/forced Blender cases each include two real CUDA processes holding a total
128 MiB of explicitly checked tensor allocations, one of them predating the
companion. All recorded process IDs disappear after owner exit. These are process
and GPU-context lifetime tests, not neural model quality tests or measurements of
VRAM belonging to unrelated applications. No computer-use automation is involved.
