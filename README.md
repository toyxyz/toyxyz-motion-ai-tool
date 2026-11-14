# Toyxyz Motion AI Tool

Generate and edit SOMA character motion in Blender using **Kimodo**, **ARDY**, and **MotionBricks**. The Windows companion runs the models locally. In Blender, use motion blocks, pose keys, paths, and control layers to author motion, then export the finished animation as FBX.

## Install on Windows

If the matching Windows companion is already installed, download and install only the Blender add-on ZIP. Keep **External App Folder** pointed at that companion.

For a fresh installation, download these two files from the [latest release](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/latest).

1. **Windows companion** — Extract [`MotionAI_Windows_Companion-0.46.3.zip`](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/download/v0.46.3/MotionAI_Windows_Companion-0.46.3.zip) and double-click `install.cmd`. It downloads Python and the default NF4 models, then displays the result until you press a key.
2. **Blender add-on** — In Blender 5.2 or later, open **Edit > Preferences > Add-ons > Install from Disk**, select [`toyxyz_motion_ai_tool-0.46.3-blender-addon.zip`](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/download/v0.46.3/toyxyz_motion_ai_tool-0.46.3-blender-addon.zip), and enable **toyxyz_motion_ai_tool**.
3. Open **Motion AI** in the 3D View sidebar and click **Start**. The add-on finds the companion installed for your Windows account. To use another copy, set **External App Folder** to the folder containing `install.cmd`.

The companion ZIP contains the installer and app files. You can skip GitHub's automatically generated **Source code (zip)** and the separate runtime volumes when using `install.cmd`.

A compatible NVIDIA GPU and driver are required for generation. Start with the [detailed guide](docs/README.md) for storage requirements, manual downloads, encoder profiles, and troubleshooting. See the [Blender workflow](docs/BLENDER_ADDON.md) and [distribution details](docs/DISTRIBUTION.md) for further reference.

