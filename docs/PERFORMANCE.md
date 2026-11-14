# VRAM and Speed

These measurements use **Windows Companion 0.46.4**, an **NVIDIA GeForce RTX 5090 (32 GB)** with driver **617.42**, and an **AMD Ryzen 9 9950X** on Windows 11. All model files were already on the local drive. Timings will vary with GPU, storage, prompts, clip length, and pose or path constraints.

## Text encoders

Kimodo and ARDY share one text encoder service. MotionBricks uses pose targets and runs without a text encoder.

| Encoder | VRAM reserved after loading | Start to ready | Encode one short new prompt after loading |
| --- | ---: | ---: | ---: |
| NF4 (default) | 4.34 GiB | 8.7–8.8 s | 52–53 ms |
| INT8 | 7.49 GiB | 9.7–13.4 s | 123–129 ms |
| BF16 | 14.26 GiB | 46.3–50.1 s | 64 ms |

**Start to ready** includes launching the encoder process, loading its weights, and initializing CUDA. The two measurements per profile came from independent Kimodo and ARDY runs. The last column shows the median for five previously unseen prompts per run. Encoder VRAM is the PyTorch reservation before the motion worker starts.

## Motion generation

| Model | Text encoder | Additional peak VRAM | First run, including loading | First run with encoder already loaded | Warm, same prompt or poses | Warm, new prompt |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Kimodo | NF4 | 6.79 GiB | 16.96 s | 8.20 s | 0.52 s | 0.57 s |
| Kimodo | INT8 | 9.54 GiB | 22.95 s | 9.58 s | 0.52 s | 0.63 s |
| Kimodo | BF16 | 17.14 GiB | 58.48 s | 8.41 s | 0.58 s | 0.59 s |
| ARDY | NF4 | 6.70 GiB | 16.53 s | 7.80 s | 0.16 s | 0.25 s |
| ARDY | INT8 | 9.56 GiB | 17.71 s | 8.02 s | 0.17 s | 0.29 s |
| ARDY | BF16 | 16.33 GiB | 55.58 s | 9.31 s | 0.17 s | 0.25 s |
| MotionBricks FP32 | — | 1.11 GiB | 2.65 s with a cached TensorRT engine | — | 0.057 s | — |

- **Kimodo and ARDY** each generated 60 model frames, or 2 seconds of forward walking, at 30 Hz. Kimodo used 30 denoising steps and ARDY used 10. Model post-processing was enabled.
- **MotionBricks** generated 30 output frames, or 1 second at 30 Hz, from three Full Body pose keys. The worker ran two model transitions and resampled them to the authored timing.
- **First run** includes the encoder process startup when applicable, motion worker startup, model loading, first-prompt or first-pose inference, and writing the result. It excludes downloads and Blender playback, NLA application, and FBX export. Filesystem caches were left in their normal Windows state.
- **Warm** keeps the motion worker and encoder in memory. The repeated-request column shows medians of five runs and can reuse a cached text embedding. The new-prompt column shows medians of three runs with text cache misses. Each run still generates the motion.
- **Additional peak VRAM** is the largest sampled GPU-wide increase above the pre-run desktop baseline, including loading and all timed requests. It includes the motion worker, encoder when applicable, and CUDA allocations. The encoder-only numbers above are included in the combined workload and should not be added again. The desktop, Blender, and other apps need their own VRAM.

In the text-driven tests, the motion worker itself peaked at **1.14 GiB** of PyTorch-reserved VRAM for Kimodo and **0.88 GiB** for ARDY. These allocator measurements exclude CUDA overhead and the separate encoder.

## Model loading during normal use

The companion keeps the current motion model loaded between jobs. Switching to another motion model loads that model on the next request. Switching text encoder profiles loads the selected encoder. **Release GPU** unloads the resident motion model and encoder. The next request then incurs the loading time again.

A first run on a new MotionBricks installation may need to build the TensorRT engine. In a separate run with an empty TensorRT cache, the first result took **77.39 s**, including the build, with **1.06 GiB** of additional sampled peak VRAM. Warm requests in that run took a median of **0.057 s**. The **2.65 s** result in the table uses an existing plan on disk. Build times and memory peaks can vary between GPUs and driver versions.
