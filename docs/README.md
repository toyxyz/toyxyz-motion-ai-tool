# Toyxyz Motion AI Tool Guide

## Requirements

- Windows x64 with PowerShell and a CUDA 12.8-compatible NVIDIA driver.
- Blender 5.2 or later. The timeline and block transitions were checked on Blender 5.2.3 LTS and 5.3.0.
- Internet access for initial runtime, model and asset downloads.
- Allow about 24 GB of free disk space for the default NF4 installation and about 35 GB for BF16. The split runtime download is about 2.94 GB, and the unpacked runtime is about 8.82 GB. Installing every encoder profile needs more space.

The companion uses its bundled CPython 3.12 environment and CUDA libraries. You can use the release without installing system Python, pip, a compiler or a separate CUDA Toolkit.

## Install the companion and Blender add-on

Blender add-on 0.46.5 works with Windows Companion 0.46.4. If Companion 0.46.4 is already installed, install the Blender add-on ZIP and leave **External App Folder** blank for automatic detection.

1. Download **`MotionAI_Windows_Companion-0.46.4.zip`** from the [Windows companion release](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/tag/windows-companion-v0.46.4) and **`toyxyz_motion_ai_tool-0.46.5-blender-addon.zip`** from the [Blender add-on release](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/latest).
2. Extract the companion ZIP to a writable folder such as `D:\MotionAI`. Use the folder that contains `install.cmd` and `runtime`. Keep the folder path free of semicolon characters. GitHub's automatically generated **Source code (zip)** is optional.
3. Double-click `install.cmd`. Use **Up/Down** to move, **Space** to check or uncheck a model, and **Enter** to confirm. All three models are checked initially. The installer verifies the Python runtime and downloads the files for the selected models. The console displays **Installation complete** or **Installation failed** and waits for a key.

   If you select Kimodo or ARDY, a second menu lets you choose **NF4**, **INT8**, **BF16**, or **All**. NF4 is checked by default. Use **Space** to select a different profile and **Enter** to confirm. MotionBricks uses its own pose model. If BF16 or All needs to download restricted files, the console displays these steps before any downloads begin.

   - Sign in, accept the license, and request access on the [Meta Llama 3 8B Instruct model page](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct). Wait for approval.
   - In the same approved account, open [Access Tokens](https://huggingface.co/settings/tokens). Choose **New token**, select **Read**, name the token, and copy it.
   - Paste the token into the hidden installer prompt. The installer uses it for the model download and does not save it. Press Enter at an empty prompt to cancel.
4. In Blender, open **Edit > Preferences > Add-ons**. Choose **Install from Disk** from the top-right menu, select the Blender add-on ZIP, and enable **toyxyz_motion_ai_tool** if required.
5. In the 3D View, press **N**, open **Motion AI**, and click **Start**. With **External App Folder** blank, Blender uses the companion registered by `install.cmd`. Set the field for a manually moved or alternate installation. Clear a saved path to return to automatic detection.
6. Add a SOMA actor and open the Motion Timeline. Choose an installed model for the active block. When the panel shows **Model files ready**, click **Generate Motion**. For missing files, use the installation command shown in the sidebar.

## Change the companion port

The default local port is **8790**. If it is already in use, choose a free port between **1024** and **65535**.

1. If the companion is running, click **Stop** in the **Motion AI** panel and wait for **Start** to reappear.
2. In Blender, open **Edit > Preferences > Add-ons**, expand **toyxyz_motion_ai_tool**, and change **Port**, for example to **8791**.
3. Click **Start** in the **Motion AI** panel. Blender starts the companion and connects on the selected port.

To start the companion manually, run this command from the companion folder. Enter the same port in Blender's add-on preferences.

```bat
toyxyz_motion_ai_tool.cmd --port 8791
```

## Install specific models or encoder profiles

Run one of these commands in the companion folder to prepare the corresponding profile:

```bat
install.cmd -Precision bf16
install.cmd -Precision int8
install.cmd -Precision nf4
install.cmd -Precision all
install.cmd -Models kimodo,ardy -Precision nf4
install.cmd -Models motionbricks -NoPause
```

Use `-Models` for a specific selection and `-NoPause` for scripts that need the installer exit code immediately. An explicit `-Precision` skips the model menu and applies to all models if `-Models` is omitted. Rerun the installer to add models. It reuses existing matching files.

Choose the matching encoder precision in Blender's Motion AI settings. New installations and new settings default to NF4. Existing saved encoder selections can still be used.

## Use manually downloaded runtime volumes

Download both `.7z.001` and `.7z.002` volumes from the [Windows companion release](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/tag/windows-companion-v0.46.4). Put them in a `downloads` folder beside `install.cmd`. Run `install.cmd` to verify and extract both volumes together, then download the model files. Use `install.cmd -RuntimeOnly` to prepare only Python. Offline generation requires the pinned model files and engine assets to be present as well. See [distribution and checksums](DISTRIBUTION.md).

## Author and export motion

- Create separate SOMA actors for independent timelines. Add ARDY or Kimodo prompt blocks, or use MotionBricks between Full Body pose keys.
- Key the source actor in Blender. The Motion Timeline supports native pose keys, optional FK/IK controls, object constraints and path curves where supported by the selected model.
- Select contiguous blocks to generate in sequence. A block can use adjacent generated clips as start and end references.
- For ARDY blocks generated one at a time, enable **Motion Post-Processing** and generate from left to right to use [shared contact cleanup](ARDY_BLOCKS.md#shared-contact-cleanup). Both blocks must provide the original model samples saved by the 0.46.4 companion.
- Add a **Control Layer** for editable corrections over generated motion. Layers can be muted, moved, trimmed or removed.
- Select an actor and choose **Export FBX** to export the evaluated motion as one animation on its SOMA skeleton.

See the [Blender workflow](BLENDER_ADDON.md), [constraint controls](KEYFRAME_CONSTRAINT_TYPES.md), [path curves](KIMODO_PATH_CURVES.md), and [local agent commands](AGENT_CONTROL.md).

## Update and troubleshoot

- Close Blender before updating the add-on. To update the companion, stop it, extract the new ZIP to a separate folder, and run its `install.cmd`. You can copy a compatible `python_embeded` folder and the existing `models` folder into the new companion folder first. The installer verifies and reuses matching files. Clear any saved **External App Folder** override to use the newly registered installation, or point it to the new folder. For a Git checkout, run `update.cmd`.
- If the companion cannot start, check **External App Folder**, run `install.cmd -Verify`, and inspect `logs/toyxyz_motion_ai_tool_app.log`. `check.cmd` runs engine import and CUDA checks.
- If model setup fails with an access error, verify your Hugging Face account's model access and retry with a read token.
- If a runtime volume is reported corrupt, replace the named volume or partial download and retry. If GPU memory is tight, prepare a smaller encoder profile and select it in Blender.
- The companion keeps prompts, pose constraints and generated outputs in `results/toyxyz_motion_ai_tool`. After stopping it, you can remove completed job folders you no longer need. Review `logs/` and diagnostic reports for local paths before sharing them.
- Review [component licenses and model distribution](DISTRIBUTION.md#third-party-components) before redistributing the packages or downloaded assets.
