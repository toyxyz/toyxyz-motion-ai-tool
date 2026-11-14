# Install and Use Motion AI with an AI Agent

Use this guide with Codex or another local agent that can run PowerShell on the Windows computer running Blender. The add-on exposes a local command interface for an open scene. The Windows companion runs motion generation. Once you enable Agent Control in Blender, an agent can author a timeline, generate motion, and export it through the CLI.

You can give your agent this page and a request like this.

> Set up Toyxyz Motion AI Tool for ARDY with the NF4 encoder. Reuse a working installation if available. After I enable Agent Control in a test scene, create a SOMA actor, generate two seconds of forward walking, and export the motion as an FBX in my project folder. Report the exported path and any Blender steps I need to take.

## 1. Install or reuse the Windows companion

Use Blender 5.2 or later and a CUDA 12.8-compatible NVIDIA driver. Check disk space before downloading the runtime and models. [Installation requirements](README.md#requirements) · [VRAM and speed](PERFORMANCE.md)

The current release pair is add-on **0.46.5** and Windows Companion **0.46.4**. Use the two named assets. The companion installer downloads the required runtime volumes and model files.

- Download the [Blender add-on ZIP](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/download/v0.46.5/toyxyz_motion_ai_tool-0.46.5-blender-addon.zip). Keep it zipped for **Install from Disk**.
- Download the [Windows companion ZIP](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/download/windows-companion-v0.46.4/MotionAI_Windows_Companion-0.46.4.zip). Extract it to a writable folder and locate `install.cmd`.

For scripted downloads, compare `Get-FileHash -Algorithm SHA256` for each ZIP with the `SHA256SUMS.txt` from its release. [Add-on checksums](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/download/v0.46.5/SHA256SUMS.txt) · [Companion checksums](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/download/windows-companion-v0.46.4/SHA256SUMS.txt)

With **External App Folder** blank, Blender finds the companion registered for the current Windows account. The installer writes the companion's `root` to `%LOCALAPPDATA%\Toyxyz\MotionAI\companion.json`. Reuse that folder if it has `install.cmd`, `runtime\entry.py`, `python_embeded\python.exe`, and the needed model files. A nonblank **External App Folder** in Blender takes precedence. The sidebar reports **Model files ready** for the active model and encoder.

From the extracted companion folder, install just the models needed for the task. These examples select ARDY and NF4 for the walkthrough. Both NF4 and INT8 use public downloads.

```powershell
$companion = 'D:\MotionAI\MotionAI_Windows_Companion-0.46.4'
Push-Location -LiteralPath $companion
try {
    .\install.cmd -Models ardy -Precision nf4 -NoPause
    if ($LASTEXITCODE -ne 0) { throw "Motion AI installation failed (exit $LASTEXITCODE)." }
} finally {
    Pop-Location
}
```

- Add Kimodo with `-Models kimodo,ardy -Precision nf4` for another text-driven option with pose and path control.
- Use `-Models motionbricks -NoPause` for MotionBricks, which connects Full Body pose keys using its own model.
- For BF16 or All, downloads of missing gated Llama files require access approval and a Hugging Face Read token from that account. The user enters it directly in the installer's hidden console prompt before downloads. Keep the token out of agent chat, commands, files, and logs. [Hugging Face access and token setup](README.md#hugging-face-access-for-bf16)

In Blender, install the add-on ZIP with **Edit > Preferences > Add-ons > Install from Disk** and enable **toyxyz_motion_ai_tool**. Open the intended file or a new test scene, then choose **3D View > Sidebar > Motion AI > Start**. Use **Enable Agent Control** in the same sidebar. Ask the user to perform these Blender steps when working through the command line. Opening another file or switching scenes in that window ends the agent session.

For the walking example, use **NF4** under **Text Encoder** if the actor already has a different profile saved. The current Agent Control commands inherit that Blender setting.

## 2. Connect the agent CLI

Run this from your project folder. Keep using the same PowerShell session for the examples below and set `$companion` to the actual companion folder if you reused an installation. The CLI is a single script from the project repository and can run with the companion's bundled Python.

```powershell
$python = Join-Path $companion 'python_embeded\python.exe'
$cli = Join-Path (Get-Location).Path 'motion_ai_agent.py'
$cliUrl = 'https://raw.githubusercontent.com/toyxyz/toyxyz-motion-ai-tool/019b17f02d0eda7c9e31bea4ec7227c195ceb70a/build_tools/motion_ai_agent.py'
if (-not (Test-Path -LiteralPath $cli)) {
    Invoke-WebRequest -Uri $cliUrl -OutFile $cli
}
& $python -X utf8 $cli list
```

Read `result` from the JSON. Match `file` and `scene` to the intended Blender window. An unsaved file has an empty `file`. Use the exact session `id` for every command. If several sessions are plausible, have the user identify the intended one before editing. You can also use `build_tools/motion_ai_agent.py` from an existing repository checkout.

The following PowerShell wrapper sends JSON via a UTF-8 file, so prompts and paths with quotes, spaces, or non-ASCII characters work across PowerShell versions. Replace the session placeholder with the ID from `list`.

```powershell
$session = 'SESSION_ID_FROM_LIST'
function Invoke-MotionAI($Command, $Arguments = @{}, [int]$Timeout = 30) {
    $argsFile = [IO.Path]::GetTempFileName()
    try {
        $payload = ConvertTo-Json -InputObject $Arguments -Depth 12 -Compress
        [IO.File]::WriteAllText($argsFile, $payload, [Text.UTF8Encoding]::new($false))
        $reply = & $python -X utf8 $cli call $Command --session $session --timeout $Timeout --args-file $argsFile | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0 -or -not $reply.ok) { throw "Motion AI ${Command}: $($reply.error)" }
        $reply.result
    } finally {
        Remove-Item -LiteralPath $argsFile
    }
}

$state = Invoke-MotionAI status
$state | ConvertTo-Json -Depth 12
```

## 3. Generate and verify a test clip

The example adds a **new** SOMA actor to a test scene. For an existing project, use the intended actor's ID and inspect its existing blocks and pose keys before editing. New actors already have a starter block. Update that block, or use `block.add` for a free range. The end frame is exclusive.

```powershell
$actor = Invoke-MotionAI actor.add @{controls = $true}
$state = Invoke-MotionAI status
$entry = $state.actors | Where-Object { $_.id -eq $actor.id }
$starter = $entry.blocks | Select-Object -First 1
$block = Invoke-MotionAI block.update @{
    actor = $actor.id
    block = $starter.id
    model = 'ardy'
    start = 1
    end = 1 + [int][Math]::Ceiling(2 * $state.fps)
    prompt = 'A person walks forward at a relaxed pace.'
}
$job = Invoke-MotionAI generate @{actor = $actor.id; blocks = @($block.id)}
$deadline = (Get-Date).AddMinutes(10)
do {
    Start-Sleep -Seconds 2
    $state = Invoke-MotionAI status
    $job = $state.job
    if ($job.status -in @('failed', 'cancelled') -or $job.application_error) {
        throw $job.message
    }
} while ($job.busy -and (Get-Date) -lt $deadline)

$entry = $state.actors | Where-Object { $_.id -eq $actor.id }
$applied = $entry.blocks | Where-Object { $_.id -eq $block.id }
if ($job.busy -or $job.status -ne 'succeeded' -or -not $applied.has_result) {
    throw "Motion was not confirmed as applied. Check status again before resubmitting. $($job.message)"
}

$exportPath = Join-Path (Get-Location).Path 'ardy-walk-test.fbx'
$export = Invoke-MotionAI export.fbx @{actor = $actor.id; filepath = $exportPath} 120
Get-Item -LiteralPath $export.filepath | Select-Object FullName, Length
```

A successful `generate` reply means the request was accepted. Poll `status` through generation and application. Report the actor, block, source frame range from the export reply, and actual file path. For an existing file, select a new output name or use `overwrite: true` when the user asked to replace it. Export uses the actor's evaluated SOMA skeleton animation. The scene's editable timeline stays open. Save the `.blend` in Blender if you want to keep the timeline and its generated motion.

## 4. Build a longer sequence

- Use `block.add` for successive ranges. For a continuous sequence, make the next block start at the previous block's exclusive end. Read the new block ID from the reply. Call `generate` with the intended actor and block IDs. When generating more than one block in a request, their ranges must touch.
- Use `actor.place` to move the entire actor. Use `frame.set` and `pose.get` to inspect the current pose, then `pose.key` for native pose keys. Use `limb.switch` when you need to switch a limb to IK or FK.
- For Kimodo or ARDY, use `path.set` with world-space points or an existing Blender Curve. Use `constraint.set` for an existing object or a world-space hand, foot, or root target. Check the generated result against its targets.
- For MotionBricks, provide two Full Body pose targets for a standalone block. A touching generated block can supply a boundary pose. Prompts are notes in MotionBricks.
- Keep the Blender session on the same scene during generation. Stop playback and finish modal edits before sending mutating commands. Use `cancel` only when the active job should stop.

[Command examples and argument reference](AGENT_CONTROL.md) · [Blender workflow](BLENDER_ADDON.md)

## Recover from setup or generation problems

| Symptom | What to check |
| --- | --- |
| `list` returns no sessions | Run under the same Windows account and temp directory as Blender. In the intended Blender window, enable Agent Control again. |
| Companion fails to start | Check **External App Folder**, the installed runtime, and the companion log at `logs/toyxyz_motion_ai_tool_app.log`. If the default port 8790 is taken, follow [Change the companion port](README.md#change-the-companion-port). The CLI uses the local agent session directory. |
| **Model files missing** or CUDA out of memory | Check the active model and **Text Encoder** in Blender. Install the missing selection, or install and select NF4 for lower encoder memory usage. |
| The command timed out after Blender picked it up | Recover the same reply with the CLI's `--request-id`, the same session, command, and arguments. See [retry behavior](AGENT_CONTROL.md#generate-and-export). |
| The job finished but has no applied result | Read `job.message` and `job.application_error`. Exit Edit Mode or NLA Tweak Mode if Blender asks. If the sidebar offers **Retry Motion Application**, use it after resolving the reported error. |

Choose **Disable Agent Control** in Blender when the agent session is finished.
