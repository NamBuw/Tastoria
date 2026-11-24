"""Fine-tune the deployed cooked_ft2 YOLO26s on the rescued 37-class dataset with a hard VRAM cap.

Appends cooked-dish 0-box negatives (from ``prepare_cooked_neg`` manifest) to train, then trains
in-process with ``torch.cuda.set_per_process_memory_fraction`` so the job can never exceed its share.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=Path("/dev/shm/yolo_v5_rescue"))
    ap.add_argument("--weights", type=Path, default=Path("/dev/shm/v3_yolo26s_640_cooked_ft2_s0_best.pt"))
    ap.add_argument("--neg-manifest", type=Path, default=Path("/dev/shm/cooked_neg/cooked_neg_manifest.txt"))
    ap.add_argument("--neg-repeat", type=int, default=2)
    ap.add_argument("--project", type=Path, default=Path("/dev/shm/det_runs"))
    ap.add_argument("--name", default="v5_yolo26s_640_rescue_s0")
    ap.add_argument("--epochs", type=int, default=14)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr0", type=float, default=0.002)
    ap.add_argument("--close-mosaic", type=int, default=4)
    ap.add_argument("--mem-fraction", type=float, default=0.20)
    a = ap.parse_args()

    added = 0
    if a.neg_manifest.is_file():
        img_dir, lbl_dir = a.data_dir / "images" / "train", a.data_dir / "labels" / "train"
        for i, ln in enumerate(a.neg_manifest.read_text(encoding="utf-8").splitlines()):
            p = Path(ln.strip())
            if not p.is_file():
                continue
            for r in range(a.neg_repeat):
                stem = f"cneg{r}_{i:05d}"
                dst = img_dir / f"{stem}.jpg"
                if not dst.exists():
                    try:
                        os.link(p, dst)
                    except OSError:
                        shutil.copy2(p, dst)
                (lbl_dir / f"{stem}.txt").write_text("", encoding="utf-8")
                added += 1
    print(f"[finetune] cooked negatives added to train: {added}", flush=True)

    import torch

    torch.cuda.set_per_process_memory_fraction(a.mem_fraction)
    from ultralytics import YOLO

    m = YOLO(str(a.weights))
    m.train(
        data=str(a.data_dir / "dataset.yaml"), epochs=a.epochs, imgsz=640, batch=a.batch, patience=6,
        seed=0, deterministic=True, workers=6, project=str(a.project), name=a.name, exist_ok=True,
        device=0, amp=True, lr0=a.lr0, lrf=0.1, warmup_epochs=1.0, cos_lr=True, close_mosaic=a.close_mosaic,
        plots=False, verbose=False,
    )
    print(f"[finetune] peak reserved GiB={torch.cuda.max_memory_reserved() / 2**30:.2f}", flush=True)


if __name__ == "__main__":
    main()

