# Toyxyz Motion AI Tool

Generate and edit SOMA character motion in Blender using **Kimodo**, **ARDY**, and **MotionBricks**. The Windows companion runs the models locally. In Blender, use motion blocks, pose keys, paths, and control layers to author motion, then export the finished animation as FBX.

## Install on Windows

Download both ZIPs from the [latest release](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/latest). Updating to 0.46.4 requires the matching companion for the new ARDY transition. Setup can reuse the existing Python runtime and model files.

1. Extract **MotionAI_Windows_Companion-0.46.4.zip** and double-click `install.cmd`. Choose the motion models and, when requested, the text encoder. The installer displays the outcome until you press a key.
2. In Blender 5.2 or later, open **Edit > Preferences > Add-ons > Install from Disk**, select **toyxyz_motion_ai_tool-0.46.4-blender-addon.zip**, and enable **toyxyz_motion_ai_tool**.
3. Open **Motion AI** in the 3D View sidebar and click **Start**. The add-on finds the companion installed for your Windows account. To use another copy, set **External App Folder** to the folder containing `install.cmd`.

The companion ZIP contains the installer and app files. You can skip GitHub's automatically generated **Source code (zip)** and the separate runtime volumes when using `install.cmd`.

A compatible NVIDIA GPU and driver are required for generation. Start with the [detailed guide](docs/README.md) for storage requirements, manual downloads, encoder profiles, and troubleshooting. See the [Blender workflow](docs/BLENDER_ADDON.md) and [distribution details](docs/DISTRIBUTION.md) for further reference.

## ARDY block transitions

When generating touching ARDY blocks one at a time, **Motion Post-Processing** can use samples from both full blocks for ARDY's native contact cleanup. The add-on preserves the existing swing animation away from predicted contacts. Regenerate the preceding block with 0.46.4 to supply its original model samples. [Behavior and eligibility](docs/ARDY_BLOCKS.md#shared-contact-cleanup).

