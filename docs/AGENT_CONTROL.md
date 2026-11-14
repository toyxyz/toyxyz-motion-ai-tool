# Control Motion AI from a local agent

For installation, the standalone CLI download, and a complete generation example, see the [agent setup and workflow guide](AGENT_GUIDE.md).

Open the working scene in Blender and click **Enable Agent Control** in the **Motion AI** sidebar. The bridge is active for that Blender window and scene. **Disable Agent Control**, switching scenes in that window or opening a `.blend` ends the session. Enable it again to work in a different scene.

From a repository checkout, run these commands using the same Windows account as Blender. Use the companion's `python_embeded\python.exe` if you do not have system Python.

```powershell
python build_tools/motion_ai_agent.py list
python build_tools/motion_ai_agent.py call status
```

The reply is JSON. `list` reports enabled Blender sessions and their command names. If several sessions are enabled, pass `--session SESSION_ID` to each call. `status` returns the current frame, frame rate, actor names and IDs, block IDs, pose key frames, curves, object constraints and generation progress. Omit `actor` to use the current Motion AI actor, or pass an actor ID or name to work on a specific rig.

## Edit an actor and its timeline

Use `call COMMAND --args-file FILE.json` to supply UTF-8 arguments. Replace the sample block ID with one from `status` or `block.add`.

| Command | Example arguments |
| --- | --- |
| `actor.add` | `{"controls":true}` |
| `actor.place` | `{"actor":"actor_01","location":[1,0,0]}` |
| `frame.set` | `{"frame":60}` |
| `block.add` | `{"start":60,"end":120,"model":"ardy","prompt":"A person turns to the left and walks forward."}` |
| `block.update` | `{"block":"BLOCK_ID","prompt":"A person slows down and comes to a stop."}` |
| `pose.get` | `{"actor":"actor_01"}` |
| `pose.key` | `{"frame":90,"root_position":[1,-0.7,1],"bones":{"Head":{"rotation":[0.98,0,0,0.2]}},"constraint":"FULL"}` |
| `limb.switch` | `{"limb":"LeftArm","ik":true}` |
| `path.set` | `{"block":"BLOCK_ID","points":[[1,0,0],[1,-1,0],[2,-2,0]],"start_percent":20}` |
| `constraint.set` | `{"frame":96,"kind":"RIGHT_HAND","location":[1.5,-0.5,1.1]}` |

Block end frames are exclusive. `block.update` can also change the model, start, end and `enabled`. `pose.get` returns current controller transforms, SOMA joint positions and limb IK states. `pose.key` writes native keys into the main pose Action. `rotation` uses a `[w,x,y,z]` quaternion. Bone names such as `Head` address the matching FK control when the control rig is present. When a limb uses IK, edit the corresponding `IK_` target and `Pole_` control. `location` inside a bone edit is local to that control. `actor.place`, `root_position`, curve points and object constraint locations use Blender world coordinates in scene units.

`pose.key` can tag a key as `FULL`, a hand or foot goal, `ROOT`, `ROOT_HEADING`, `ROOT_HEIGHT` or `ROOT_HEADING_HEIGHT`. Combine partial types with `+`. `constraint.set` can also reference an existing independent Blender object with `target`. Root object goals accept `root_heading` and `root_height`. Generation uses these markers as motion targets, so model support and reach still affect the result.

`path.set` creates a Blender Curve from the supplied points for an ARDY or Kimodo block. Pass `curve` with an existing Curve object name to use that shape. Pass only `block` and an optional `actor` to unlink the path.

## Generate and export

Call `generate` with `{"blocks":["BLOCK_ID"]}` to use those blocks, or call it with empty arguments to use the actor's timeline selection. It starts the same companion workflow as **Generate Motion**. Use `status` to read `job.status`, `job.busy`, `job.progress` and application errors. The job is complete when the generation result has been applied and `job.busy` is false. `cancel` cancels the current scene's job. The existing model limitations still apply. MotionBricks uses Full Body pose targets and treats the prompt as notes.

Call `export.fbx` with `{"filepath":"D:/MotionOutput/actor.fbx"}` to save the selected actor's motion on the SOMA skeleton. Use an absolute path in an existing folder. Set `overwrite` to `true` when replacing an existing file. For long exports, increase the CLI reply timeout with `--timeout 120`.

If Blender picks up a command but the reply times out, the CLI prints its request ID. Within ten minutes, retry with `--request-id` and the same command and arguments in the same enabled session to recover the previous reply. Wait for the original CLI call to exit before retrying.

The interface accepts only the listed commands over a local per-session directory. It runs Blender edits on Blender's main thread and replies with an error while playback or a modal edit is in progress. Scene edits stay in the open file until you save them in Blender.
