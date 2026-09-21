"""Real pose `Detector`, per #4.2: ultralytics YOLOv8-pose."""

from __future__ import annotations

import ctypes
import gc
from typing import Any

import numpy as np

from edl_agent.features._common import Detection, Detector


def free_torch_memory() -> int:
    """Release freed torch/CUDA allocator pages back to the OS.

    Call after `del`-eting the detector built by `yolo_pose_detector`,
    once no more inference will run in this process (P0 light-device
    work: candidates hold ~3 GB resident otherwise, inflating every
    later stage's RSS, e.g. the render peak).

    Runs `gc.collect()` (drops the torch objects), empties the CUDA
    cache when torch is importable, then `malloc_trim` so glibc
    actually returns pages to the OS instead of hoarding them.

    Returns:
        Bytes reclaimed by `malloc_trim` (`1`/`0` truthy fallback when
        glibc is unavailable, e.g. non-Linux).
    """
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
    try:
        return int(ctypes.CDLL("libc.so.6").malloc_trim(0))
    except OSError:
        return 1


def yolo_pose_detector(model_path: str = "yolov8n-pose.pt") -> Detector:
    """Build the real pose `Detector`, per #4.2: ultralytics YOLOv8-pose.

    Uses a lazy import so the rest of the module does not depend on
    torch/ultralytics in unit tests.

    Args:
        model_path: Path or model name to load with `ultralytics.YOLO`.
            Defaults to `"yolov8n-pose.pt"`.

    Returns:
        A `Detector` callable: takes a BGR frame and returns a list of
        `Detection`s with bbox and keypoints normalized to the frame's
        width/height. Keypoints are all-zero if the model returns none.
    """
    from ultralytics import YOLO

    model = YOLO(model_path)

    def _detect(frame_bgr: np.ndarray) -> list[Detection]:
        h, w = frame_bgr.shape[:2]
        predictions: Any = model.predict(frame_bgr, verbose=False)
        result = predictions[0]
        dets: list[Detection] = []
        if result.boxes is None:
            return dets
        boxes = result.boxes.xyxy.cpu().numpy()
        kpts = (
            result.keypoints.data.cpu().numpy()
            if result.keypoints is not None
            else None
        )
        for i, box in enumerate(boxes):
            x0, y0, x1, y1 = (float(v) for v in box)
            bbox = (x0 / w, y0 / h, x1 / w, y1 / h)
            if kpts is not None:
                kp = kpts[i].copy()
                kp[:, 0] /= w
                kp[:, 1] /= h
            else:
                kp = np.zeros((17, 3))
            dets.append(Detection(bbox=bbox, keypoints=kp))
        return dets

    return _detect
