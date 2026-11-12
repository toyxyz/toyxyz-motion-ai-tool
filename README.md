# Toyxyz Motion AI Tool

Generate and edit SOMA character motion in Blender using **Kimodo**, **ARDY**, and **MotionBricks**. The Windows companion runs the models locally. In Blender, use motion blocks, pose keys, paths, and control layers to author motion, then export the finished animation as FBX.

## Install on Windows

1. Open the [latest release](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/latest). Download and extract **Source code (zip)**, then download the **Blender add-on ZIP**.
2. Run `install.cmd` from the extracted source folder. It downloads the embedded Python runtime and model files. The default BF16 encoder may prompt for a Hugging Face read token with access to Meta Llama 3.
3. In Blender 5.2 or later, open **Edit > Preferences > Add-ons > Install from Disk**, select the add-on ZIP, and enable **toyxyz_motion_ai_tool**.
4. Set **External App Folder** in the add-on preferences to the folder containing `install.cmd`. Open **Motion AI** in the 3D View sidebar and click **Start**.

A compatible NVIDIA GPU and driver are required for generation. Start with the [detailed guide](docs/README.md) for storage requirements, manual downloads, encoder profiles, and troubleshooting. See the [Blender workflow](docs/BLENDER_ADDON.md) and [distribution details](docs/DISTRIBUTION.md) for further reference.

