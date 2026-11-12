# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Step (1) of evaluation pipeline.

This script builds the benchmark test suites from BVH motions in the Bones-SEED dataset using the
benchmark metadata. Currently it is only set up for the SOMA skeleton.

The released metadata (``seed_motion.json`` / ``seed_constraints.json``) is representation-agnostic:
it only records the BVH crop and the constraint types + frame indices. The motion representation
enters here, when the ground-truth motion and the constraint values are rehydrated from the BVH:

- ``--motion_rep kimodo`` (default, the released benchmark): root constraints are read off the
  ADMM-smoothed root trajectory (``smooth_root_pos``); the GT motion is canonicalized on the
  smooth root at frame 0.
- ``--motion_rep ardy``: root constraints are read off the raw hips trajectory (ardy has no smooth
  root; ``smooth_root_pos`` is an alias of ``root_positions``); the GT motion is canonicalized on
  the hips at frame 0. Everything else (crop, fps, T-pose, constraint frame indices, file names)
  is identical, so the two suites are the *same* test cases with rep-appropriate targets.

Use ``--output`` to build the suite into a separate tree (the metadata files are copied over), so
that e.g. an ardy suite can be built next to the kimodo one from the same seeds.
"""

import argparse
import shutil
from functools import partial
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import torch
from tqdm import tqdm

from kimodo.geometry import matrix_to_axis_angle
from kimodo.motion_rep.reps import ArdyMotionRep, KimodoMotionRep
from kimodo.skeleton import SOMASkeleton30, SOMASkeleton77
from kimodo.skeleton.bvh import parse_bvh_motion
from kimodo.tools import load_json, save_json, to_numpy, to_torch

FPS = 30
BENCHMARK_REPO_ID = "nvidia/Kimodo-Motion-Gen-Benchmark"

MOTION_REPS = {"kimodo": KimodoMotionRep, "ardy": ArdyMotionRep}
SEED_FILES = ("meta.json", "seed_motion.json", "seed_constraints.json")
# keys of the rep-agnostic gt_motion.npz written for every rep (same set as the released suite)
GT_MOTION_KEYS = (
    "posed_joints",
    "root_positions",
    "smooth_root_pos",
    "global_root_heading",
    "local_rot_mats",
    "global_rot_mats",
    "foot_contacts",
)


def download_benchmark(dest: Path) -> Path:
    """Download the benchmark testsuite from HuggingFace to *dest*."""
    from huggingface_hub import snapshot_download

    print(f"Downloading benchmark testsuite from {BENCHMARK_REPO_ID} to {dest} ...")
    snapshot_dir = snapshot_download(
        repo_id=BENCHMARK_REPO_ID,
        repo_type="dataset",
        local_dir=str(dest),
    )
    return Path(snapshot_dir)


def discover_seed_motion_folders(root: Path) -> list[Path]:
    """Find all directories under root that contain seed_motion.json; return sorted list of those
    dirs."""
    root = root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Folder does not exist: {root}")
    out: list[Path] = []
    for meta_path in root.rglob("seed_motion.json"):
        src_dir = meta_path.parent
        out.append(src_dir)
    return sorted(out)


def load_seed_motion(seed_motion: dict, dataset_folder: Path, skeleton, fps: int):
    """Parse the BVH referenced by ``seed_motion`` into standard-T-pose local rotations and root
    translations at ``fps`` on ``skeleton`` (full motion, not cropped)."""
    bvh_path = dataset_folder / seed_motion["bvh_path"].replace("BVH/", "bvh/")

    local_rot_mats, root_trans, bvh_fps = parse_bvh_motion(bvh_path)
    step = round(bvh_fps / fps)

    # Subsample fps
    root_trans = root_trans[::step]
    local_rot_mats = local_rot_mats[::step]

    # Changing t_pose: essential step (the BVH is on the 77-joint SOMA skeleton)
    skel77 = skeleton if isinstance(skeleton, SOMASkeleton77) else SOMASkeleton77()
    local_rot_mats, _ = skel77.to_standard_tpose(local_rot_mats)
    if isinstance(skeleton, SOMASkeleton30):
        local_rot_mats = skeleton.from_SOMASkeleton77(local_rot_mats)
    return local_rot_mats, root_trans


def gt_motion_from_seed(seed_motion: dict, dataset_folder: Path, motion_rep, fps: int) -> dict:
    """Rehydrate the cropped, canonicalized GT motion dict of a test case through ``motion_rep``."""
    local_rot_mats, root_trans = load_seed_motion(seed_motion, dataset_folder, motion_rep.skeleton, fps)

    start = seed_motion["crop_start_frame_index"]
    end = seed_motion["crop_end_frame_index"]

    # Use the motion rep to canonicalize the motion (start z+ at 0,0)
    # and get other components (smooth root for kimodo, foot contacts etc)
    feats = motion_rep(local_rot_mats, root_trans, to_normalize=False)

    # Crop the features and canonicalizing them
    feats = feats[start:end]
    can_feats = motion_rep.canonicalize(feats)
    # Get back the motion
    motion = motion_rep.inverse(can_feats, is_normalized=False)
    motion = {k: motion[k] for k in GT_MOTION_KEYS}
    return to_numpy(to_torch(motion, dtype=torch.float32))


def constraints_from_seed(seed_constraints_lst: list[dict], motion: dict) -> list[dict]:
    """Fill the released constraint metadata (type + frame indices) with target values read off the
    GT motion. For ardy ``smooth_root_pos`` is the raw hips trajectory."""
    constraints_lst = []
    for seed_cons in seed_constraints_lst:
        cons = seed_cons.copy()
        frame_indices = cons["frame_indices"]

        cons["smooth_root_2d"] = motion["smooth_root_pos"][frame_indices][..., [0, 2]].tolist()

        if cons["type"] == "root2d":
            if cons.get("use_global_orient", False):
                cons["global_root_heading"] = motion["global_root_heading"][frame_indices].tolist()  # noqa
        elif cons["type"] in ["fullbody"] or cons["type"] in [
            "left-hand",
            "right-hand",
            "left-foot",
            "right-foot",
            "end-effector",
        ]:
            cons["local_joints_rot"] = matrix_to_axis_angle(to_torch(motion["local_rot_mats"][frame_indices])).tolist()
            cons["root_positions"] = motion["root_positions"][frame_indices].tolist()
        else:
            raise TypeError(f"This constraint type is not recognized: {cons['type']}")

        constraints_lst.append(cons)
    return constraints_lst


def constraints_and_motion_from_seed(
    folder: str,
    dataset_folder: str,
    motion_rep_name: str = "kimodo",
    output_folder: str | None = None,
    fps=FPS,
):
    """Load seed_motion.json and BVH from folder; subsample to fps, convert to SOMA gt_motion.npz
    and constraints. With ``output_folder`` the results (and the seed metadata) are written there
    instead of in place."""
    folder = Path(folder)
    dataset_folder = Path(dataset_folder)
    out_folder = Path(output_folder) if output_folder is not None else folder
    if out_folder != folder:
        out_folder.mkdir(parents=True, exist_ok=True)
        for name in SEED_FILES:
            if (folder / name).is_file():
                shutil.copy2(folder / name, out_folder / name)

    # the suite is always baked on the full 77-joint SOMA skeleton (as released); 30-joint model
    # outputs are upscaled at evaluation time
    skeleton = SOMASkeleton77()
    motion_rep = MOTION_REPS[motion_rep_name](skeleton, fps)

    seed_motion = load_json(folder / "seed_motion.json")
    motion = gt_motion_from_seed(seed_motion, dataset_folder, motion_rep, fps)
    np.savez(out_folder / "gt_motion.npz", **motion)

    seed_constraints_path = folder / "seed_constraints.json"
    if seed_constraints_path.exists():
        constraints_lst = constraints_from_seed(load_json(seed_constraints_path), motion)
        save_json(out_folder / "constraints.json", constraints_lst)


def main():
    parser = argparse.ArgumentParser(
        description="Recursively find test case to fill with motions and constraints.",
    )
    parser.add_argument(
        "benchmark",
        type=Path,
        help="Root folder to search recursively or seed_motion.json for to download the benchmark testsuite from HuggingFace to.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default="datasets/bones-seed/soma_uniform",
        help="SEED dataset folder",
    )
    parser.add_argument(
        "--motion_rep",
        choices=sorted(MOTION_REPS),
        default="kimodo",
        help="Motion representation used to rehydrate GT motions and constraint targets: "
        "'kimodo' (smooth-root, the released benchmark) or 'ardy' (raw hips root).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write gt_motion.npz / constraints.json (plus copies of the seed metadata) into this "
        "folder, mirroring the benchmark hierarchy, instead of in place.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Redo the process even if gt_motion.npz already exists",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel worker processes (default: 1, sequential)",
    )
    args = parser.parse_args()

    folder = args.benchmark.resolve()
    if not folder.is_dir():
        print(f"Benchmark folder not found at {folder}, downloading from HuggingFace...")
        download_benchmark(folder)

    dirs = discover_seed_motion_folders(folder)
    if not dirs:
        raise SystemExit(f"No directories with seed_motion.json found under {folder}")
    print(f"Discovered {len(dirs)} motion to populate.")

    output = args.output.resolve() if args.output is not None else None

    def out_dir(d: Path) -> Path:
        return output / d.relative_to(folder) if output is not None else d

    skipped = 0
    to_process = []
    for d in dirs:
        if not args.overwrite and (out_dir(d) / "gt_motion.npz").is_file():
            skipped += 1
        else:
            to_process.append(d)

    fn = partial(
        constraints_and_motion_from_seed,
        dataset_folder=args.dataset,
        motion_rep_name=args.motion_rep,
    )
    jobs = [(fn, d, str(out_dir(d)) if output is not None else None) for d in to_process]
    with Pool(args.workers) as pool:
        list(
            tqdm(
                pool.imap_unordered(_run_job, jobs),
                total=len(jobs),
                desc=f"Extracting GT motions ({args.motion_rep})",
            )
        )

    if skipped:
        print(f"Processed {len(dirs) - skipped} folders, skipped {skipped} (already present).")
    else:
        print("Saved gt_motion.npz and constraints.json from the seed files.")


def _run_job(job):
    """Pool entry point: ``(fn, folder, output_folder)``."""
    fn, folder, output_folder = job
    return fn(folder, output_folder=output_folder)


if __name__ == "__main__":
    main()
