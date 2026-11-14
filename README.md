# Toyxyz Motion AI Tool

Generate and edit SOMA character motion in Blender using **Kimodo**, **ARDY**, and **MotionBricks**. The Windows companion runs the models locally. In Blender, use motion blocks, pose keys, paths, and control layers to author motion, then export the finished animation as FBX.

## Demo

https://github.com/user-attachments/assets/936f82a2-da96-4285-83be-b85a2f0fd369

## Install on Windows

Download the [Blender add-on](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/latest) and the [Windows companion](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/tag/windows-companion-v0.46.4) from their separate releases. Add-on 0.46.5 works with Windows Companion 0.46.4. Setup can reuse the existing Python runtime and model files.

1. Extract **MotionAI_Windows_Companion-0.46.4.zip** and double-click `install.cmd`. Choose the motion models and, when requested, the text encoder. The installer displays the outcome until you press a key.
2. In Blender 5.2 or later, open **Edit > Preferences > Add-ons > Install from Disk**, select **toyxyz_motion_ai_tool-0.46.5-blender-addon.zip**, and enable **toyxyz_motion_ai_tool**.
3. Open **Motion AI** in the 3D View sidebar and click **Start**. Leave **External App Folder** blank to find the companion installed for your Windows account. To use another copy, set it to the folder containing `install.cmd`.

The companion ZIP contains the installer and app files. You can skip GitHub's automatically generated **Source code (zip)** and the separate runtime volumes when using `install.cmd`.

The default **NF4** setup requires no Hugging Face token. Downloading the gated **BF16** files requires Meta Llama model access and a Hugging Face **Read** token. [Token setup](docs/README.md#hugging-face-access-for-bf16)

A compatible NVIDIA GPU and driver are required for generation. See the [installation guide](docs/README.md) for storage, [port changes](docs/README.md#change-the-companion-port), and troubleshooting. See [VRAM and speed](docs/PERFORMANCE.md) for measurements by model and text encoder, and the [Blender workflow](docs/BLENDER_ADDON.md) for motion authoring and FBX export.

Using Codex or another local AI agent? Share the [agent setup and workflow guide](docs/AGENT_GUIDE.md) for installation, scene control, motion generation, and FBX export.

## ARDY block transitions

When generating touching ARDY blocks one at a time, **Motion Post-Processing** can use samples from both full blocks for ARDY's native contact cleanup. The add-on preserves the existing swing animation away from predicted contacts. Regenerate the preceding block with Windows Companion 0.46.4 to supply its original model samples. [Behavior and eligibility](docs/ARDY_BLOCKS.md#shared-contact-cleanup).

