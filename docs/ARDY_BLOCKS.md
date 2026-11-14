# ARDY Blocks

Choose **ARDY** as a motion block's **Model**, enter a prompt and set its length by dragging its timeline edges. Select one or more touching enabled blocks and click **Generate Motion**. Generation uses the external embedded-Python app, then automatically applies native NLA strips on the existing SOMA rig. User correction Actions remain separate. There is no live Start/Stop recording session in this implementation.

## Lengths and internal windows

The installed `ARDY-SOMA-RP-30FPS-Horizon60` model runs at **30 FPS**, predicts a **60-frame** horizon and uses **4-frame** tokens. These are internal sizes, not a maximum animation length. The worker repeatedly advances bounded autoregressive windows until it has exactly the requested output. Partial windows are trimmed, so neither block boundaries nor output lengths need to be multiples of 4 or 60. Prompts switch at each block boundary, including non-token-aligned boundaries; history is padded at its old end when needed to preserve token alignment.

The output minimum is **one model frame** (about 0.033 seconds). At scene FPS F, the timeline minimum is `ceil(F/30)` scene frames: one at 30 FPS, two at 60 FPS. With motion post-processing enabled, one-frame outputs also receive their pose corrections. When ARDY's predicted horizontal step matches the preceding motion, automatic continuation carries that step into the new block while keeping the inherited joint pose and hip height. Explicit constraints near the start retain their normal priority. There is **no model-imposed total duration maximum**. ARDY-only selections therefore bypass the previous 60-second operation cap and do not have a 15-minute worker timeout; Cancel remains available. The existing 32-block selection limit, Blender frame range, memory and storage remain application limits. Mixed-model selections retain their existing 60-second operation cap.

The model is trained with windows of up to 10 seconds. Each step uses at most **240 frames / 8 seconds** of prior motion plus the 60-frame / 2-second prediction horizon. With shorter history, remaining window capacity can expose future pose/path constraints. This history is cropped between steps instead of growing with the entire requested animation. Long output still occupies memory and native Action keys when stored; no duration-independent total memory claim is made.

## Inputs and continuity

- **Prompt** changes by block; a sequence retains generated motion history across those changes.
- Ordinary native SOMA bone keys become full-body pose constraints, using the composed generated base plus user correction layer, as in the existing addon.
- **Path Curve** uses the shared-curve grouping behavior for touching blocks of the same model. ARDY's root constraint refers to raw hips XZ, while Kimodo uses smoothed root XZ. Curve height is ignored; posture/height use generation or pose targets.
- An adjacent existing clip can supply up to 240 canonical SOMA history frames, including user corrections. This also permits continuation after Kimodo or MotionBricks without modifying the preceding Action. Existing Start keys remain constraints. A gap does not supply a moving history tail.
- **Advanced** contains ARDY's own denoising steps (**1–10**, default **10**), Motion Post-Processing, Text Guidance and Constraint Guidance. Kimodo's Transition Overlap control is not shown for ARDY: its autoregressive history is a separate model mechanism.
- BF16/INT8/NF4 use the existing shared text encoder service. One resident motion worker is kept until another motion model is selected for generation, Release GPU is clicked, or a worker fails/is cancelled. Switching motion engines keeps the compatible shared encoder.

ARDY produces a 30-joint body representation, expanded with the official SOMA conversion to the addon’s 77 joints. It does not independently author fine finger motion.

## Shared contact cleanup

With Blender add-on 0.46.5 and Windows Companion 0.46.4, enable **Motion Post-Processing**, generate an ARDY block, then generate the touching ARDY block to its right. If ARDY predicts that the same foot is in contact across the boundary, its native post-processing uses the full sequence of original model samples from the two blocks. The existing transition supplies the swing-leg animation away from predicted contacts. The result is stored in the **Motion AI · Block Transitions** NLA track above the source Actions.

- The previous block can change during playback. Its generated Action remains available underneath the transition track. Mute that track in the NLA Editor to review the underlying clips.
- When a following generation creates another eligible pair, both native solves use complete input blocks. Their playback ranges meet at the midpoint of the shared block and ease back to the generated motion at that handoff.
- Shared cleanup uses blocks with unchanged strip timing and boundaries aligned to the model's 30 Hz samples. Authored pose keys, object constraints, path curves, or a correction boundary layer can cause Blender to use its ordinary transition behavior to protect the authored motion.
- To supply full-block samples for an older scene, regenerate the preceding block with Windows Companion 0.46.4 before generating its neighbor. Existing short transition results can still play in saved projects.

Selecting multiple touching ARDY blocks in one **Generate Motion** command produces one continuous model result. The worker carries its generated history across prompts and applies native post-processing to the sequence.

## Validation

`results/blender_bridge/ardy_blocks.json` covers actual Blender RNA, duration bounds and requests beyond 60 seconds, shared routes including one-frame cases, pose targets, model-specific controls and save/reopen. `ardy_generation.json` covers real GPU inference and native NLA application: a 61/65-frame sequence, one-frame continuation and a 1801-frame rollout with 31 windows and at most 240 history frames. `ardy_mixed.json` covers Kimodo -> ARDY -> MotionBricks -> ARDY and source Action/slot/key preservation. These checks use separate factory-startup background Blender processes; the user's GUI is not automated. Successful execution and numerical checks do not establish general motion quality or manual UI acceptance.

Official references: [ARDY project](https://research.nvidia.com/labs/sil/projects/ardy/), [official repository](https://github.com/nv-tlabs/ardy). The pinned local model configuration and `autoregressive_step` implementation were inspected to distinguish the 60-frame prediction horizon, four-frame tokens and bounded history from total output duration.
