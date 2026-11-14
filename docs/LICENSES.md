# Model and Third-Party Licenses

Built with Meta Llama 3.

This guide covers Blender add-on 0.46.5 and Windows Companion 0.46.4. The [engine manifest](../manifests/engines.lock.json) records source revisions. The [model and asset manifest](../manifests/models.lock.json) records the installed files, revisions, and SHA-256 hashes. The linked license texts provide the terms for each component.

## Motion models

| Component | Engine source code | Model terms |
| --- | --- | --- |
| Kimodo · `Kimodo-SOMA-RP-v1.2` | [Apache-2.0](../engines/kimodo/LICENSE) | **NVIDIA Open Model License Agreement**, October 24, 2025. [Pinned license](https://huggingface.co/nvidia/Kimodo-SOMA-RP-v1.2/blob/0e3c89024d896064b6851201373f7834784a386b/LICENSE) · [Pinned model card](https://huggingface.co/nvidia/Kimodo-SOMA-RP-v1.2/blob/0e3c89024d896064b6851201373f7834784a386b/README.md) |
| ARDY · `ARDY-SOMA-RP-30FPS-Horizon60` | [Apache-2.0](../engines/ardy/LICENSE) | The pinned `LICENSE` contains the **NVIDIA Open Model License Agreement** from October 24, 2025. The pinned model card points to the **NVIDIA Open Model Agreement** from April 2, 2026. [Pinned license](https://huggingface.co/nvidia/ARDY-SOMA-RP-30FPS-Horizon60/blob/244215084b22fcd29ab743017330e87411fe168a/LICENSE) · [Pinned model card](https://huggingface.co/nvidia/ARDY-SOMA-RP-30FPS-Horizon60/blob/244215084b22fcd29ab743017330e87411fe168a/README.md) |
| MotionBricks · SOMA ONNX | [Apache-2.0](../engines/motionbricks/LICENSE) | **NVIDIA Open Model Agreement**, April 2, 2026. The Companion installs `mmm_v6_soma_fp32.onnx`. The notice also covers the FP16 ONNX file listed for the source checkout. [Pinned ONNX notice](../engines/motionbricks/motionbricks/assets/onnx/LICENSE.md) · [Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-agreement/) |

Both NVIDIA agreements permit commercial use subject to their terms, and NVIDIA states that it claims no ownership of generated outputs. For ARDY, both the downloaded `LICENSE` and the model card are preserved by the installer. Ask NVIDIA to confirm which text governs if you plan to redistribute the checkpoint and need to resolve the discrepancy. [October 2025 agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/) · [April 2026 agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-agreement/)

The Companion ZIP includes the engine code and its notices. Setup fetches the motion weights directly from the pinned upstream sources. When redistributing weights or modified models, consult the applicable agreement's redistribution section for the license-copy and attribution requirements.

## Text encoders for Kimodo and ARDY

| Profile | Installed components | License and access |
| --- | --- | --- |
| NF4 | Voxta's merged 4-bit Llama 3 / LLM2Vec encoder | **Meta Llama 3 Community License Agreement** and its Acceptable Use Policy. Public download. [Pinned NF4 model card](https://huggingface.co/voxta/Llama-3-8B-LLM2Vec-ARDY-NF4/blob/f746923e9e7edb3b6fc54aae7dfd8cecb0f52a8f/README.md) |
| INT8 | Voxta's merged 8-bit Llama 3 / LLM2Vec encoder | **Meta Llama 3 Community License Agreement** and its Acceptable Use Policy. Public download. [Pinned INT8 model card](https://huggingface.co/voxta/Llama-3-8B-LLM2Vec-ARDY-INT8/blob/96c7eb1cc9100cd3925662d1093926c00b64a698/README.md) |
| BF16 | Meta Llama 3 8B Instruct and the McGill NLP LLM2Vec MNTP and supervised adapters | The base model uses the **Meta Llama 3 Community License Agreement** and its Acceptable Use Policy. McGill NLP labels both adapter repositories **MIT**. The installer requires repository access and a Hugging Face Read token when the gated Meta files need downloading. [Meta model card](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct) · [Pinned MNTP adapter card](https://huggingface.co/McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp/blob/31474e395ada192e8ed1586db6be79fb3b70c9c0/README.md) · [Pinned supervised adapter card](https://huggingface.co/McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised/blob/baa8ebf04a1c2500e61288e7dad65e8ae42601a7/README.md) |

Public downloads still carry the stated license and use terms. The MIT labels on the adapter repositories apply to those components. The Meta agreement sets its own conditions for products and services using Llama 3, including distribution, attribution, and additional commercial terms for organizations that meet its user threshold. MotionBricks runs without a text encoder. [Meta license and acceptable use terms](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct/blob/main/LICENSE) · [BF16 access instructions](README.md#hugging-face-access-for-bf16)

## Sample motion, preview assets, and runtime

- **MotionBricks sample motions.** The listed Bones-derived BVH and CSV clips use the **NVIDIA Sample Data Evaluation License**. It permits internal evaluation and testing of NVIDIA technologies. The license bars distribution of these clips and their derivative works. The upstream demo workflow in the source checkout can download the pinned BVHs. The packaged Companion installer fetches only the SOMA USD and FP32 ONNX files for MotionBricks. [Sample list and credits](../engines/motionbricks/assets/motions/README.md) · [Sample data license](../engines/motionbricks/assets/motions/LICENSE.txt)
- **MotionBricks documentation and assets.** The upstream source license identifies **CC BY 4.0** for its documentation, skills, and assets. Follow the specific notices for ONNX weights, sample motions, and third-party assets. [MotionBricks license file](../engines/motionbricks/LICENSE) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
- **SOMA preview.** The Blender preview uses the `skin_standard.npz` file included with Kimodo or ARDY in the Companion. Third-party body models and rigs bring their own terms. The preview asset and any imported rig or motion used in a project should be reviewed separately from the license for inference. [Preview asset provenance](SOMA_PREVIEW_MESH.md) · [SOMA-X project license and third-party notes](https://github.com/NVlabs/SOMA-X#license)
- **Companion runtime.** The embedded Python environment keeps the Python and dependency license files. The packaged 7-Zip executable has its own notice. CUDA, cuDNN, and the installed TensorRT runtime packages have separate NVIDIA terms. [Distribution details](DISTRIBUTION.md#third-party-components) · [7-Zip notice](../bootstrap/tools/7zip/License.txt) · [TensorRT terms](https://docs.nvidia.com/deeplearning/tensorrt/latest/reference/sla.html)

This document records third-party terms for the release. The repository has no separate project-wide license declaration for Toyxyz-authored code.
