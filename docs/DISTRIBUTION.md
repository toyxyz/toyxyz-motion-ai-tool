# Source and Runtime Distribution

The [Blender add-on release](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/latest) provides the ZIP for Blender. The separate [Windows companion release](https://github.com/toyxyz/toyxyz-motion-ai-tool/releases/tag/windows-companion-v0.46.4) provides the companion ZIP and the pinned Python runtime volumes. See the [installation and workflow guide](README.md) for the end-user steps.

## Layout

```text
toyxyz_motion_ai_tool/
  addons/toyxyz_motion_ai_tool/   Blender addon source and SOMA metadata
  runtime/                      Companion app, workers, shared encoder, demo manager
  engines/                      Pinned Kimodo, ARDY and MotionBricks source and licenses
  bootstrap/                    Windows bootstrap, verifier and 7-Zip
  build_tools/                  Local packaging, deployment and validation tools
  manifests/                    Runtime, engine and model versions and hashes
  install.cmd                   Prepare runtime and models
  toyxyz_motion_ai_tool.cmd      Start the Blender companion app
  launch.cmd                    Start the original model demo manager
  update.cmd                    Fast-forward source update and prepare dependencies
  check.cmd                     Check all three engines and CUDA
  python_embeded/               Separate runtime distribution, ignored by Git
    python.exe
    python312.dll / python312.zip
    environment.json / environment.files.json
    packages/common/
    packages/kimodo/
    packages/ardy/
    packages/motionbricks/
  models/                       Separate model downloads, ignored by Git
  settings.json                 User settings, ignored by Git
  downloads/ .install/           Archive volumes, staging and receipts, ignored by Git
  cache/ logs/ results/ testdata/  Local data, ignored by Git
```

Python and required packages travel together as one `python_embeded` folder. Large shared packages are stored once; engine-specific version differences have private directories. Every AI worker uses this environment, never Blender's Python.

## End-user installation

Extract **`MotionAI_Windows_Companion-0.46.4.zip`** from the Windows companion release. It contains the Blender companion application, installer, engine code and required assets for the Blender workflow. The GitHub source archive also contains upstream demos and developer tooling.

1. Run `install.cmd` and choose one or more motion models. New text-encoder installations default to NF4. For a scripted selection, pass `-Models kimodo,ardy` or any combination of `kimodo`, `ardy`, and `motionbricks`. Select another encoder profile with `-Precision bf16`, `-Precision int8`, or `-Precision all`.
2. A matching `python_embeded` folder is reused. Its first adoption verifies all immutable runtime files.
3. If missing, all pinned split volumes are downloaded and checked against their SHA-256 hashes. A `.partial` download resumes when the server supports HTTP Range.
4. Extraction occurs inside `.install/stage_*`. The staged version, critical files, complete file manifest, Python isolation and UTF-8 native host are verified before activation.
5. Replaced environments are retained under `.install/previous_*`. Active workers are not replaced. Failed staging folders are retained for inspection.
6. Files for the selected models are fetched from pinned upstream locations. When BF16 needs gated Llama files, enter a Hugging Face Read token from the approved account at the hidden console prompt. The installer uses the token for those downloads and does not save it. See [token setup and troubleshooting](README.md#hugging-face-access-for-bf16).

Use `install.cmd -RuntimeOnly` to prepare only the runtime. For a full recheck of a specific installation, use `install.cmd -Verify -Models <list>` and pass the matching encoder profile if needed.

## Manual and offline preparation

Copy a verified `python_embeded` folder into the source root, or place every `.7z.001`, `.7z.002`, etc. volume in `downloads` and run the installer. For another volume directory, use `-DownloadDirectory "D:\Runtime Parts"`. Do not extract each volume separately.

The default runtime URL is pinned in `manifests/runtime.lock.json`. For a mirror, supply `-RuntimeBaseUrl` followed by its HTTPS base URL. Loopback HTTP is available for local tests.

## Updates

`update.cmd` runs `git pull --ff-only` when the checkout has Git and an origin, then prepares the runtime and models pinned by that source revision. With no Git checkout, runtime preparation still works. Local source conflicts are not discarded. Existing models, results, settings and caches are preserved.

An unchanged runtime ID avoids another large download. An updated runtime is staged and verified before activation. Ordinary source edits do not require rebuilding the Python environment.

Windows Companion 0.46.4 works with Blender add-on 0.46.5 and supplies full-block ARDY transition data. Restart both applications after replacing the companion files. The companion release hosts the existing runtime revision with the same hashes.

## Developer packaging

Build the Blender add-on and curated Companion ZIP from a tracked Git tree with `python build_tools/package_blender_release.py --output dist`. Run the release checks on the packaged files before publishing.

```bat
python_embeded\python.exe -X utf8 build_tools\package_runtime.py --output distribution
```

The packager uses 7-Zip Ultra, LZMA2, a 256 MiB dictionary, 16 threads, and 1536 MiB volumes. Only `python_embeded` is archived. Models, source, settings, caches and bytecode caches are excluded. CRC testing and per-volume SHA-256 recording follow packaging. Output files are not silently overwritten. Nothing is uploaded.

Current archive: 2,939,315,421 bytes in two volumes of 1,610,612,736 and 1,328,702,685 bytes. Each is below 2 GiB. Current uncompressed immutable payload is 8,818,235,014 bytes.

`environment.files.json` pins immutable environment files. `runtime.lock.json` pins that manifest's hash and the release volumes. When package/native runtime content changes, create a new runtime ID and manifest before packaging.

Publish the add-on ZIP on the Blender release and publish the companion ZIP and runtime volumes on the companion release. Pin the companion's versioned runtime download URL in `publication.base_url`. Verify the runtime assets at the new URL before retiring an older release that hosts them.

## Validation boundaries

Local clone/pull, actual split HTTP download with an 8 MiB resume point, extraction, complete runtime checks, corrupted-volume rejection, environment reuse and Unicode paths were tested. A separate clean Windows machine remains untested. Use an installation path free of semicolon characters.

The original monolithic lab assemblers have been retired for this source checkout. Use the current `build_tools` and pinned manifests. Upstream licenses remain with engine sources and runtime packages.

## Third-party components

The engine source includes the licenses and notices listed in [the engine manifest](../manifests/engines.lock.json). The embedded runtime preserves its package license files and the Python Software Foundation license. CUDA and cuDNN components remain subject to their NVIDIA terms. See the [CUDA Toolkit agreement](https://docs.nvidia.com/cuda/archive/12.8.0/eula/index.html) and the [cuDNN agreement](https://docs.nvidia.com/deeplearning/cudnn/latest/reference/eula.html).

The [model and asset manifest](../manifests/models.lock.json) lists the upstream downloads, revisions and checksums. Model weights and downloaded motion data use their respective upstream terms.
