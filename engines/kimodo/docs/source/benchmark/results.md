# Kimodo Results

On this page, we report the results for the latest Kimodo models on the benchmark test suite. These results are reproducible with the [evaluation pipeline](pipeline.md) and should be used when comparing against other models. Note that the reported numbers differ from the numbers in the [tech report](https://research.nvidia.com/labs/sil/projects/kimodo/assets/kimodo_tech_report.pdf) (Sec. 6) due to differences in skeleton, test suite composition, and evaluation details.

To reproduce these results or evaluate your own model, follow the [evaluation pipeline](pipeline.md) and use `parse_folder --format md` to generate summary tables in markdown format.

**Note on reproducibility**: to exactly reproduce the results in the tables below, use batch size 1 when generating with Kimodo (i.e., when running `generate_eval.py`). This way, every test case is individually seeded according to `meta.json`. The reported results were computed using LLM2Vec in the default `bfloat16` precision. However, the Kimodo-SOMA-v1.1 and TMR models were actually trained with `float32` embeddings, so if you want to get the best possible performance (and you have enough VRAM), you can include `--text_encoder_fp32` when running the generation and embedding steps, even though the results will not match the tables here.

**Update (2026-10-15)**: the Kimodo-SOMA-SEED-v1.1 and Kimodo-SOMA-RP-v1.1 results below were recomputed with TF32 disabled (full `float32` matrix multiplications). They were originally computed in an NVIDIA PyTorch container, which enables TF32 by default (`TORCH_ALLOW_TF32_CUBLAS_OVERRIDE=1`); the reduced precision adds small frame-to-frame noise to the generated motions, which raised foot skating (Skate) by about 0.3–0.4 cm/s, while the other metrics changed only slightly (see [#52](https://github.com/nv-tlabs/kimodo/issues/52)). The benchmark scripts (`generate_eval.py`, `embed_folder.py`, `evaluate_folder.py`) now always disable TF32, so results no longer depend on the environment. The previously published numbers are available in the [earlier version of this page](https://github.com/nv-tlabs/kimodo/blob/58e781898b3d7e328a676a75d3e338c45dce3ad9/docs/source/benchmark/results.md).

Results are reported on the two splits described in [the introduction](introduction.md#dataset-splits):

- **Content**: test cases with novel semantic content not present in training (e.g. unseen action categories).
- **Repetition**: content categories seen during training, but specific motion clips are held out and unseen. Note that due to the annotations in Bones Rigplay and SEED datasets, the text prompts in this test split have already been seen during training.

For each split, we also report metrics for the ground truth motion. These rows serve as an empirical upper bound for motion quality, and deviations between ground truth and generated metrics highlight where the model can improve.

We split results for each model into two tables corresponding to different test cases in the test suite:

- **Text-Following**: `overview`, `timeline_single`, and `timeline_multi`
- **Constrained**: `constraints_withtext`, `constraints_notext`

<!-- 
## Kimodo-SOMA-SEED-v1.1
These results are for the Kimodo model trained on the public [BONES-SEED](https://huggingface.co/datasets/bones-studio/seed) dataset. The results are comparable to any model trained on SEED that uses our recommended splits [described in the introduction](introduction.md#dataset-splits).

### Text-Following Evaluation

|  | Overview R@3↑ | Overview FID↓ | Overview Skate↓ | Overview Contact↑ | Timeline single R@3↑ | Timeline single FID↓ | Timeline single Skate↓ | Timeline single Contact↑ | Timeline multi R@3↑ | Timeline multi FID↓ | Timeline multi Skate↓ | Timeline multi Contact↑ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Content** Ground Truth | 89.09 | 0.000 | 1.849 | 1.000 | 86.37 | 0.000 | 1.789 | 1.000 | 88.09 | 0.000 | 1.711 | 1.000 |
| **Content** Kimodo | 81.13 | 0.035 | 3.703 | 0.978 | 73.50 | 0.029 | 3.535 | 0.981 | 80.23 | 0.033 | 3.302 | 0.981 |
| **Repetition** Ground Truth | 94.03 | 0.000 | 2.106 | 1.000 | 90.04 | 0.000 | 2.037 | 1.000 | 94.55 | 0.000 | 1.931 | 1.000 |
| **Repetition** Kimodo | 91.05 | 0.004 | 4.238 | 0.972 | 80.08 | 0.007 | 4.134 | 0.976 | 92.64 | 0.006 | 3.861 | 0.975 |


### Constrained Evaluation

|  | With text FB Pos↓ | With text EE Pos↓ | With text EE Rot↓ | With text 2D Root↓ | With text Pelvis@95% | Without text FB Pos↓ | Without text EE Pos↓ | Without text EE Rot↓ | Without text 2D Root↓ | Without text Pelvis@95% |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Content** Ground Truth | 0.000 | 0.000 | - | 3.837 | 5.36 | 0.000 | 0.000 | - | 3.913 | 5.41 |
| **Content** Kimodo | 3.419 | 3.817 | - | 4.976 | 9.17 | 3.320 | 3.665 | - | 4.801 | 9.03 |
| **Repetition** Ground Truth | 0.000 | 0.000 | - | 3.607 | 5.44 | 0.000 | 0.000 | - | 3.567 | 5.42 |
| **Repetition** Kimodo | 3.186 | 3.849 | - | 4.733 | 9.18 | 3.119 | 3.510 | - | 4.265 | 7.89 |



## Kimodo-SOMA-RP-v1.1
These results are for the Kimodo model trained on the full (proprietary) Bones Rigplay dataset which is a superset of BONES-SEED. Though the training split is larger, the model is not trained on the SEED test splits to ensure a fair comparison.

### Text-Following Evaluation

|  | Overview R@3↑ | Overview FID↓ | Overview Skate↓ | Overview Contact↑ | Timeline single R@3↑ | Timeline single FID↓ | Timeline single Skate↓ | Timeline single Contact↑ | Timeline multi R@3↑ | Timeline multi FID↓ | Timeline multi Skate↓ | Timeline multi Contact↑ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Content** Ground Truth | 89.09 | 0.000 | 1.849 | 1.000 | 86.37 | 0.000 | 1.789 | 1.000 | 88.09 | 0.000 | 1.711 | 1.000 |
| **Content** Kimodo | 83.32 | 0.025 | 3.235 | 0.983 | 78.19 | 0.026 | 3.156 | 0.984 | 84.79 | 0.028 | 2.861 | 0.985 |
| **Repetition** Ground Truth | 94.03 | 0.000 | 2.106 | 1.000 | 90.04 | 0.000 | 2.037 | 1.000 | 94.55 | 0.000 | 1.931 | 1.000 |
| **Repetition** Kimodo | 87.82 | 0.008 | 3.738 | 0.978 | 77.06 | 0.011 | 3.598 | 0.981 | 88.59 | 0.009 | 3.355 | 0.980 |


### Constrained Evaluation

|  | With text FB Pos↓ | With text EE Pos↓ | With text EE Rot↓ | With text 2D Root↓ | With text Pelvis@95% | Without text FB Pos↓ | Without text EE Pos↓ | Without text EE Rot↓ | Without text 2D Root↓ | Without text Pelvis@95% |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Content** Ground Truth | 0.000 | 0.000 | - | 3.837 | 5.36 | 0.000 | 0.000 | - | 3.913 | 5.41 |
| **Content** Kimodo | 2.925 | 3.027 | - | 4.582 | 7.77 | 2.932 | 2.991 | - | 4.411 | 7.37 |
| **Repetition** Ground Truth | 0.000 | 0.000 | - | 3.607 | 5.44 | 0.000 | 0.000 | - | 3.567 | 5.42 |
| **Repetition** Kimodo | 2.802 | 2.979 | - | 4.259 | 7.62 | 2.827 | 2.968 | - | 4.028 | 7.21 |
-->


## Quantitative Results

Results are reported for two models:

- **Kimodo-SOMA-SEED-v1.1**:  trained on the public [BONES-SEED](https://huggingface.co/datasets/bones-studio/seed) dataset. The results are comparable to any model trained on SEED that uses our recommended splits [described in the introduction](introduction.md#dataset-splits).
- **Kimodo-SOMA-RP-v1.1**: trained on the full (proprietary) Bones Rigplay dataset which is a superset of BONES-SEED. Though the training split is larger, the model is not trained on the SEED test splits to ensure a fair comparison. **Update (2026-10-15)**: we have since found that some BONES-SEED test sequences had leaked into v1.1's training set; when comparing against the benchmark, prefer the corrected models in [Updated Models (v1.2)](#updated-models-v12).

### Text-Following Evaluation

|  | Overview R@3↑ | Overview FID↓ | Overview Skate↓ | Overview Contact↑ | Timeline single R@3↑ | Timeline single FID↓ | Timeline single Skate↓ | Timeline single Contact↑ | Timeline multi R@3↑ | Timeline multi FID↓ | Timeline multi Skate↓ | Timeline multi Contact↑ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Content** Ground Truth | 89.09 | 0.000 | 1.849 | 1.000 | 86.37 | 0.000 | 1.789 | 1.000 | 88.09 | 0.000 | 1.711 | 1.000 |
| **Content** Kimodo-SOMA-SEED-v1.1 | 81.13 | 0.035 | 3.703 | 0.978 | 73.50 | 0.029 | 3.535 | 0.981 | 80.23 | 0.033 | 3.302 | 0.981 |
| **Content** Kimodo-SOMA-RP-v1.1 | 83.32 | 0.025 | 3.235 | 0.983 | 78.19 | 0.026 | 3.156 | 0.984 | 84.79 | 0.028 | 2.861 | 0.985 |
| **Repetition** Ground Truth | 94.03 | 0.000 | 2.106 | 1.000 | 90.04 | 0.000 | 2.037 | 1.000 | 94.55 | 0.000 | 1.931 | 1.000 |
| **Repetition** Kimodo-SOMA-SEED-v1.1 | 91.05 | 0.004 | 4.238 | 0.972 | 80.08 | 0.007 | 4.134 | 0.976 | 92.64 | 0.006 | 3.861 | 0.975 |
| **Repetition** Kimodo-SOMA-RP-v1.1 | 87.82 | 0.008 | 3.738 | 0.978 | 77.06 | 0.011 | 3.598 | 0.981 | 88.59 | 0.009 | 3.355 | 0.980 |

### Constrained Evaluation

|  | With text FB Pos↓ | With text EE Pos↓ | With text EE Rot↓ | With text 2D Root↓ | With text Pelvis@95% | Without text FB Pos↓ | Without text EE Pos↓ | Without text EE Rot↓ | Without text 2D Root↓ | Without text Pelvis@95% |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Content** Ground Truth | 0.000 | 0.000 | - | 3.837 | 5.36 | 0.000 | 0.000 | - | 3.913 | 5.41 |
| **Content** Kimodo-SOMA-SEED-v1.1 | 3.419 | 3.817 | - | 4.976 | 9.17 | 3.320 | 3.665 | - | 4.801 | 9.03 |
| **Content** Kimodo-SOMA-RP-v1.1 | 2.925 | 3.027 | - | 4.582 | 7.77 | 2.932 | 2.991 | - | 4.411 | 7.37 |
| **Repetition** Ground Truth | 0.000 | 0.000 | - | 3.607 | 5.44 | 0.000 | 0.000 | - | 3.567 | 5.42 |
| **Repetition** Kimodo-SOMA-SEED-v1.1 | 3.186 | 3.849 | - | 4.733 | 9.18 | 3.119 | 3.510 | - | 4.265 | 7.89 |
| **Repetition** Kimodo-SOMA-RP-v1.1 | 2.802 | 2.979 | - | 4.259 | 7.62 | 2.827 | 2.968 | - | 4.028 | 7.21 |

## Updated Models (v1.2)

Two updated Rigplay models are trained on **corrected training splits**: in Kimodo-SOMA-RP-v1.1, some
BONES-SEED test sequences had leaked into the training set, so the v1.1 RP rows above are not fully
comparable to models trained on the recommended splits (note that SEED models are not affected). The models below remove the leaked sequences —
use them as the reference point when comparing against the benchmark:

- **Kimodo-SOMA-RP-v1.2**: same smooth-root motion representation as v1.1.
- **Kimodo-SOMA-RP-ArdyRep-v1.2**: predicts the Ardy motion representation (global root / global
  joints, raw hips as the root — no smooth root). Build its test suite with
  `create_benchmark.py --motion_rep ardy`.

**Protocol note**: the rows below follow the same protocol as the tables above — batch size 1
(every test case individually seeded from its `meta.json`), the LLM2Vec text encoder in the default
`bfloat16` precision, and full-fp32 matrix multiplications (TF32 disabled, which the benchmark
scripts now enforce). Exact commands: `generate_eval.py --model <model> --batch_size 1`, then
`embed_folder.py` and `evaluate_folder.py` with default settings. The Ground Truth rows are
re-embedded on the same machine as the generated motions; across different GPUs / PyTorch builds,
`bfloat16` embeddings can shift R@3 by up to ~0.5 while Skate and FID are stable.

**Root-metric caveat**: the ArdyRep rows are evaluated on the ardy-rep test suite, where the root
constraint targets the raw hip trajectory and Ground Truth scores 0 by construction; the
smooth-root rows target the smoothed root, where Ground Truth itself scores ~3.6-3.9 cm. The
2D Root and Pelvis columns are therefore not comparable between the two representations.

### Text-Following Evaluation

|  | Overview R@3↑ | Overview FID↓ | Overview Skate↓ | Overview Contact↑ | Timeline single R@3↑ | Timeline single FID↓ | Timeline single Skate↓ | Timeline single Contact↑ | Timeline multi R@3↑ | Timeline multi FID↓ | Timeline multi Skate↓ | Timeline multi Contact↑ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Content** Ground Truth | 88.66 | 0.000 | 1.849 | 1.000 | 86.37 | 0.000 | 1.789 | 1.000 | 88.21 | 0.000 | 1.711 | 1.000 |
| **Content** Kimodo-SOMA-RP-v1.2 | 79.83 | 0.037 | 3.331 | 0.982 | 72.19 | 0.034 | 3.191 | 0.983 | 81.75 | 0.037 | 2.965 | 0.984 |
| **Content** Kimodo-SOMA-RP-ArdyRep-v1.2 | 80.70 | 0.034 | 3.580 | 0.980 | 72.96 | 0.033 | 3.387 | 0.983 | 82.51 | 0.034 | 3.133 | 0.984 |
| **Repetition** Ground Truth | 93.95 | 0.000 | 2.106 | 1.000 | 89.96 | 0.000 | 2.037 | 1.000 | 94.44 | 0.000 | 1.931 | 1.000 |
| **Repetition** Kimodo-SOMA-RP-v1.2 | 85.97 | 0.010 | 3.945 | 0.975 | 74.33 | 0.013 | 3.696 | 0.978 | 86.96 | 0.012 | 3.517 | 0.978 |
| **Repetition** Kimodo-SOMA-RP-ArdyRep-v1.2 | 85.97 | 0.009 | 4.148 | 0.973 | 74.54 | 0.012 | 3.908 | 0.978 | 87.41 | 0.011 | 3.670 | 0.977 |

### Constrained Evaluation

|  | With text FB Pos↓ | With text EE Pos↓ | With text EE Rot↓ | With text 2D Root↓ | With text Pelvis@95% | Without text FB Pos↓ | Without text EE Pos↓ | Without text EE Rot↓ | Without text 2D Root↓ | Without text Pelvis@95% |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Content** Ground Truth (smooth root) | 0.000 | 0.000 | - | 3.837 | 5.36 | 0.000 | 0.000 | - | 3.912 | 5.41 |
| **Content** Kimodo-SOMA-RP-v1.2 | 2.967 | 3.216 | - | 4.658 | 7.76 | 2.987 | 3.154 | - | 4.500 | 7.55 |
| **Content** Kimodo-SOMA-RP-ArdyRep-v1.2 (raw-hips root, GT 0) | 3.063 | 3.434 | - | 2.904 | 6.79 | 3.101 | 3.383 | - | 2.637 | 5.93 |
| **Repetition** Ground Truth (smooth root) | 0.000 | 0.000 | - | 3.607 | 5.44 | 0.000 | 0.000 | - | 3.567 | 5.42 |
| **Repetition** Kimodo-SOMA-RP-v1.2 | 2.953 | 3.264 | - | 4.416 | 8.15 | 2.900 | 3.142 | - | 4.104 | 7.34 |
| **Repetition** Kimodo-SOMA-RP-ArdyRep-v1.2 (raw-hips root, GT 0) | 3.064 | 3.387 | - | 2.835 | 7.08 | 2.984 | 3.289 | - | 2.405 | 5.38 |
