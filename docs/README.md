# Toyxyz Motion AI Tool Guide

## Requirements

- Windows x64 with PowerShell and a CUDA 12.8-compatible NVIDIA driver.
- Blender 5.2 or later. The add-on was tested on Blender 5.2.3 LTS.
- Internet access for initial runtime, model and asset downloads.
- About 35 GB of free disk space for a new BF16 installation, including retained download volumes and room for setup. The split runtime download is about 2.94 GB. The unpacked runtime is about 8.82 GB. The BF16 model and asset downloads total about 19.5 GB. Installing every encoder profile needs more space.

The companion uses its bundled CPython 3.12 environment and CUDA libraries. You can use the release without installing system Python, pip, a compiler or a separate CUDA Toolkit.

## Install the companion and Blender add-on

1. Open the [release page](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/tag/v0.46.1). Download **Source code (zip)** and **`toyxyz_motion_ai_tool-0.46.1-blender-addon.zip`**.
2. Extract **Source code (zip)** to a writable folder such as `D:\MotionAI`. Use the folder that contains `install.cmd` and `runtime`. Keep the folder path free of semicolon characters.
3. Open Command Prompt in that folder and run:

   ```bat
   install.cmd
   ```

   The installer downloads both runtime volumes, checks their SHA-256 hashes, extracts the embedded Python environment and downloads the pinned model files. If prompted for a Hugging Face token, use a read token from an account that has been granted access to [Meta Llama 3 8B Instruct](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct). The installer accepts the token at a hidden prompt.
4. In Blender, open **Edit > Preferences > Add-ons**. Choose **Install from Disk** from the top-right menu, select **`toyxyz_motion_ai_tool-0.46.1-blender-addon.zip`**, and enable **toyxyz_motion_ai_tool** if required.
5. Expand the add-on preferences. Set **External App Folder** to the extracted folder containing `install.cmd`. Save preferences if needed.
6. In the 3D View, press **N**, open **Motion AI**, and click **Start**. Add a SOMA actor and open the Motion Timeline. Select a prompt block, then click **Generate Motion**.

## Choose an encoder profile

Run one of these commands in the companion folder to prepare the corresponding profile:

```bat
install.cmd -Precision bf16
install.cmd -Precision int8
install.cmd -Precision nf4
install.cmd -Precision all
```

Choose the matching encoder precision in Blender's Motion AI settings. BF16 is the default. INT8 and NF4 use less encoder memory and can produce different motion. Kimodo and ARDY use the text encoder. MotionBricks generates between Full Body pose targets and uses its own model.

## Use manually downloaded runtime volumes

Download both `.7z.001` and `.7z.002` assets from the same release. Put them in a `downloads` folder beside `install.cmd`. Run `install.cmd` to verify and extract both volumes together, then download the model files. Use `install.cmd -RuntimeOnly` to prepare only Python. Offline generation requires the pinned model files and engine assets to be present as well. See [distribution and checksums](DISTRIBUTION.md).

## Author and export motion

- Create separate SOMA actors for independent timelines. Add ARDY or Kimodo prompt blocks, or use MotionBricks between Full Body pose keys.
- Key the source actor in Blender. The Motion Timeline supports native pose keys, optional FK/IK controls, object constraints and path curves where supported by the selected model.
- Select contiguous blocks to generate in sequence. A block can use adjacent generated clips as start and end references.
- Add a **Control Layer** for editable corrections over generated motion. Layers can be muted, moved, trimmed or removed.
- Select an actor and choose **Export FBX** to export the evaluated motion as one animation on its SOMA skeleton.

See the [Blender workflow](BLENDER_ADDON.md), [constraint controls](KEYFRAME_CONSTRAINT_TYPES.md), [path curves](KIMODO_PATH_CURVES.md), and [local agent commands](AGENT_CONTROL.md).

## Update and troubleshoot

- Close Blender and stop the companion before replacing their files. For a source ZIP installation, extract the next release to a separate folder and point Blender at that folder after installing the matching add-on ZIP. You can copy a compatible `python_embeded` folder and the existing `models` folder into the new source folder before running `install.cmd`. The installer verifies and reuses matching files. For a Git checkout, run `update.cmd`.
- If the companion cannot start, check **External App Folder**, run `install.cmd -Verify`, and inspect `logs/toyxyz_motion_ai_tool_app.log`. `check.cmd` runs engine import and CUDA checks.
- If model setup fails with an access error, verify your Hugging Face account's model access and retry with a read token.
- If a runtime volume is reported corrupt, replace the named volume or partial download and retry. If GPU memory is tight, prepare a smaller encoder profile and select it in Blender.
- Review [component licenses and model distribution](DISTRIBUTION.md#third-party-components) before redistributing the packages or downloaded assets.
