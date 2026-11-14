# Toyxyz Motion AI Tool Guide

## Requirements

- Windows x64 with PowerShell and a CUDA 12.8-compatible NVIDIA driver.
- Blender 5.2 or later. The add-on was tested on Blender 5.2.3 LTS.
- Internet access for initial runtime, model and asset downloads.
- Allow about 24 GB of free disk space for the default NF4 installation and about 35 GB for BF16. The split runtime download is about 2.94 GB, and the unpacked runtime is about 8.82 GB. Installing every encoder profile needs more space.

The companion uses its bundled CPython 3.12 environment and CUDA libraries. You can use the release without installing system Python, pip, a compiler or a separate CUDA Toolkit.

## Install the companion and Blender add-on

If the matching Windows companion is already installed, install only the Blender add-on ZIP and keep **External App Folder** pointed at that companion.

1. From the [release page](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/tag/v0.46.2), download **`MotionAI_Windows_Companion-0.46.2.zip`** and **`toyxyz_motion_ai_tool-0.46.2-blender-addon.zip`**.
2. Extract the companion ZIP to a writable folder such as `D:\MotionAI`. Use the folder that contains `install.cmd` and `runtime`. Keep the folder path free of semicolon characters. GitHub's automatically generated **Source code (zip)** is optional.
3. Open Command Prompt in that folder and run:

   ```bat
   install.cmd
   ```

   The installer downloads and verifies both runtime volumes, extracts Python, and downloads the pinned NF4 models. The default NF4 encoder is publicly downloadable. If you choose BF16, use a read token from an account with access to [Meta Llama 3 8B Instruct](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct) at the hidden prompt.
4. In Blender, open **Edit > Preferences > Add-ons**. Choose **Install from Disk** from the top-right menu, select the Blender add-on ZIP, and enable **toyxyz_motion_ai_tool** if required.
5. In the 3D View, press **N**, open **Motion AI**, and click **Start**. Blender uses the companion registered by `install.cmd`. Set **External App Folder** in the add-on preferences for a manually moved or alternate installation.
6. When the panel shows **Model files ready**, add a SOMA actor and open the Motion Timeline. Select a prompt block, then click **Generate Motion**. For missing files, use the installation command shown in the sidebar.

## Choose an encoder profile

Run one of these commands in the companion folder to prepare the corresponding profile:

```bat
install.cmd -Precision bf16
install.cmd -Precision int8
install.cmd -Precision nf4
install.cmd -Precision all
```

Choose the matching encoder precision in Blender's Motion AI settings. New installations and new settings default to NF4. Existing saved encoder selections can still be used. Kimodo and ARDY use the text encoder. MotionBricks generates between Full Body pose targets using its own model.

## Use manually downloaded runtime volumes

Download both `.7z.001` and `.7z.002` volumes from the [v0.46.1 runtime release](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/tag/v0.46.1). Put them in a `downloads` folder beside `install.cmd`. Run `install.cmd` to verify and extract both volumes together, then download the model files. Use `install.cmd -RuntimeOnly` to prepare only Python. Offline generation requires the pinned model files and engine assets to be present as well. See [distribution and checksums](DISTRIBUTION.md).

## Author and export motion

- Create separate SOMA actors for independent timelines. Add ARDY or Kimodo prompt blocks, or use MotionBricks between Full Body pose keys.
- Key the source actor in Blender. The Motion Timeline supports native pose keys, optional FK/IK controls, object constraints and path curves where supported by the selected model.
- Select contiguous blocks to generate in sequence. A block can use adjacent generated clips as start and end references.
- Add a **Control Layer** for editable corrections over generated motion. Layers can be muted, moved, trimmed or removed.
- Select an actor and choose **Export FBX** to export the evaluated motion as one animation on its SOMA skeleton.

See the [Blender workflow](BLENDER_ADDON.md), [constraint controls](KEYFRAME_CONSTRAINT_TYPES.md), [path curves](KIMODO_PATH_CURVES.md), and [local agent commands](AGENT_CONTROL.md).

## Update and troubleshoot

- Close Blender and stop the companion before replacing their files. For a companion ZIP installation, extract the next release to a separate folder and point Blender at that folder after installing the matching add-on ZIP. You can copy a compatible `python_embeded` folder and the existing `models` folder into the new companion folder before running `install.cmd`. The installer verifies and reuses matching files. For a Git checkout, run `update.cmd`.
- If the companion cannot start, check **External App Folder**, run `install.cmd -Verify`, and inspect `logs/toyxyz_motion_ai_tool_app.log`. `check.cmd` runs engine import and CUDA checks.
- If model setup fails with an access error, verify your Hugging Face account's model access and retry with a read token.
- If a runtime volume is reported corrupt, replace the named volume or partial download and retry. If GPU memory is tight, prepare a smaller encoder profile and select it in Blender.
- The companion keeps prompts, pose constraints and generated outputs in `results/toyxyz_motion_ai_tool`. After stopping it, you can remove completed job folders you no longer need. Review `logs/` and diagnostic reports for local paths before sharing them.
- Review [component licenses and model distribution](DISTRIBUTION.md#third-party-components) before redistributing the packages or downloaded assets.
