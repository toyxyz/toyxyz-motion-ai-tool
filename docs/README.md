# Toyxyz Motion AI Tool Guide

## Requirements

- Windows x64 with PowerShell and a CUDA 12.8-compatible NVIDIA driver.
- Blender 5.2 or later. The timeline and block transitions were checked on Blender 5.2.3 LTS and 5.3.0.
- Internet access for initial runtime, model and asset downloads.
- Allow about 24 GB of free disk space for the default NF4 installation and about 35 GB for BF16. The split runtime download is about 2.94 GB, and the unpacked runtime is about 8.82 GB. Installing every encoder profile needs more space.

The companion uses its bundled CPython 3.12 environment and CUDA libraries. You can use the release without installing system Python, pip, a compiler or a separate CUDA Toolkit.

See [VRAM and speed](PERFORMANCE.md) for measured GPU memory, first-run time and generation speed after loading for each model and text encoder profile.

## Install the companion and Blender add-on

Blender add-on 0.46.5 works with Windows Companion 0.46.4. If Companion 0.46.4 is already installed, install the Blender add-on ZIP and leave **External App Folder** blank for automatic detection.

1. Download **`MotionAI_Windows_Companion-0.46.4.zip`** from the [Windows companion release](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/tag/windows-companion-v0.46.4) and **`toyxyz_motion_ai_tool-0.46.5-blender-addon.zip`** from the [Blender add-on release](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/latest).
2. Extract the companion ZIP to a writable folder such as `D:\MotionAI`. Use the folder that contains `install.cmd` and `runtime`. Keep the folder path free of semicolon characters. GitHub's automatically generated **Source code (zip)** is optional.
3. Double-click `install.cmd`. Use **Up/Down** to move, **Space** to check or uncheck a model, and **Enter** to confirm. All three models are checked initially. The installer verifies the Python runtime and downloads the files for the selected models. The console displays **Installation complete** or **Installation failed** and waits for a key.

   If you selected Kimodo or ARDY, use **Space** and **Enter** in the second menu to choose a text encoder. **NF4** is the default. See [Hugging Face access for BF16](#hugging-face-access-for-bf16) if you choose **BF16** or **All**.
4. In Blender, open **Edit > Preferences > Add-ons**. Choose **Install from Disk** from the top-right menu, select the Blender add-on ZIP, and enable **toyxyz_motion_ai_tool** if required.
5. In the 3D View, press **N**, open **Motion AI**, and click **Start**. With **External App Folder** blank, Blender uses the companion registered by `install.cmd`. Set the field for a manually moved or alternate installation. Clear a saved path to return to automatic detection.
6. Under **SOMA Rigs**, click **Add**, then click **Open Motion Timeline**. Choose an installed model for the active block. When the panel shows **Model files ready**, click **Generate Motion**. For missing files, run the installation command shown in the sidebar from the companion folder.

## Hugging Face access for BF16

| Installer selection | Hugging Face token |
| --- | --- |
| Kimodo or ARDY with **NF4** (default) or **INT8** | No token for the currently pinned public downloads |
| Kimodo or ARDY with **BF16** or **All** | A Read token is required when the gated Llama files need to be downloaded. The installer reuses files that pass its checks. |
| **MotionBricks** only | Uses its own pose model and skips the text encoder menu and token prompt |
| **Runtime only** (`-RuntimeOnly`) | Installs the Python runtime without a token |

1. Sign in to Hugging Face, accept the license and submit the access request on the [Meta Llama 3 8B Instruct model page](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct). Wait for access to be approved.
2. In the same account, open [Access Tokens](https://huggingface.co/settings/tokens). Choose **New token**, select **Read**, give it a name, and copy it. Approval is tied to the account that created the token. [Hugging Face token guide](https://huggingface.co/docs/hub/security-tokens)
3. Run `install.cmd` in a Windows console. Select Kimodo or ARDY and **BF16** or **All**. When matching Llama files are missing or need replacement, the hidden console prompt appears before runtime or model downloads. Paste the token there. Press **Enter** with an empty prompt to cancel.

The installer uses the token only to download the gated Llama files. It does not store the token in Blender, companion settings, or a Hugging Face login cache. The installed models run locally without the token.

If Hugging Face returns **401** or **403**, confirm that the account can access the Llama files in your browser, then create a Read token from that account and rerun the installer. Choose **NF4** or **INT8** to install the public encoder files while access is pending.

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

Use `-Models` for a specific selection. When `-Models` is omitted, command-line installation checks all three models. Options such as `-Models`, `-Precision`, `-Verify`, and `-NoPause` skip the interactive selection menus. `-NoPause` also skips the final keypress. If new BF16 files require a token, run the command in a Windows console with interactive input. Rerun the installer to add models or profiles. It reuses existing matching files.

Choose **Text Encoder** in Blender's Motion AI panel when a Kimodo or ARDY block is active. Match it to one of the profiles you installed. **All** installs every profile. Blender runs one selected profile per job.

## Use manually downloaded runtime volumes

Download both `.7z.001` and `.7z.002` volumes from the [Windows companion release](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/tag/windows-companion-v0.46.4). Put them in a `downloads` folder beside `install.cmd`. Run `install.cmd` to verify and extract both volumes together, then download the model files. Use `install.cmd -RuntimeOnly` to prepare only Python. Offline generation requires the pinned model files and engine assets to be present as well. See [distribution and checksums](DISTRIBUTION.md).

## Author and export motion

- Create separate SOMA actors for independent timelines. Choose **Kimodo** for text prompts with pose or path control. Choose **ARDY** for text-driven locomotion and longer sequences. Choose **MotionBricks** to connect **Full Body** pose keys. Its **Notes** field is for your own reference.
- For a first MotionBricks block, key a start and a destination pose inside the block. A generated clip before the block can supply the start pose, and a touching generated clip after it can supply the destination. See [MotionBricks timing](BLENDER_ADDON.md#duration-bounds).
- Key the source actor in Blender. The Motion Timeline supports native pose keys, optional FK/IK controls, object constraints and path curves where supported by the selected model.
- Select contiguous blocks to generate in sequence. A block can use adjacent generated clips as start and end references.
- For ARDY blocks generated one at a time, enable **Motion Post-Processing** and generate from left to right to use [shared contact cleanup](ARDY_BLOCKS.md#shared-contact-cleanup). Both blocks must provide the original model samples saved by the 0.46.4 companion.
- Add a **Control Layer** for editable corrections over generated motion. Layers can be muted, moved, trimmed or removed.
- Select an actor and choose **Export FBX** to export the evaluated motion as one animation on its SOMA skeleton.

See the [Blender workflow](BLENDER_ADDON.md), [constraint controls](KEYFRAME_CONSTRAINT_TYPES.md), [path curves](KIMODO_PATH_CURVES.md), [ARDY blocks](ARDY_BLOCKS.md), and [local agent commands](AGENT_CONTROL.md).

## Update and troubleshoot

- Close Blender before updating the add-on. To update the companion, stop it, extract the new ZIP to a separate folder, and run its `install.cmd`. You can copy a compatible `python_embeded` folder and the existing `models` folder into the new companion folder first. The installer verifies and reuses matching files. Clear any saved **External App Folder** override to use the newly registered installation, or point it to the new folder. For a Git checkout, run `update.cmd`.
- If the companion cannot start, check **External App Folder**, run `check.cmd` for runtime and CUDA checks, and inspect `logs/toyxyz_motion_ai_tool_app.log`. To check model files by SHA-256, rerun setup with the installed selection, for example `install.cmd -Verify -Models ardy -Precision nf4`.
- If a runtime volume is reported corrupt, replace the named volume or partial download and retry. If GPU memory is tight, prepare a smaller encoder profile and select it in Blender.
- The companion keeps prompts, pose constraints and generated outputs in `results/toyxyz_motion_ai_tool`. After stopping it, you can remove completed job folders you no longer need. Review `logs/` and diagnostic reports for local paths before sharing them.
- Review [component licenses and model distribution](DISTRIBUTION.md#third-party-components) before redistributing the packages or downloaded assets.
