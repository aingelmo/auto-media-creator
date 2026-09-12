"""Parquet (de)serialization of a `features` dict."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pathlib import Path


def save_features(features: dict, path: Path) -> None:
    """Serialize a `features` dict (from `extract.extract_features`) to Parquet.

    Args:
        features: Feature series dict, as returned by
            `extract.extract_features`.
        path: Output `.parquet` path (parent directory created if
            missing).
    """
    import pandas as pd

    bbox = features["subject_bbox"]
    df = pd.DataFrame(
        {
            "t_s": features["t_s"],
            "kp_speed": features["kp_speed"],
            "motion_bg": features["motion_bg"],
            "motion": features["motion"],
            "sharpness": features["sharpness"],
            "subject_visible": features["subject_visible"],
            "multi_subject": features["multi_subject"],
            "bbox_x0": [b[0] if b else np.nan for b in bbox],
            "bbox_y0": [b[1] if b else np.nan for b in bbox],
            "bbox_x1": [b[2] if b else np.nan for b in bbox],
            "bbox_y1": [b[3] if b else np.nan for b in bbox],
        }
    )
    df.attrs["features_config_sha256"] = features["features_config_sha256"]
    df.attrs["n_tracks"] = features["n_tracks"]
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def load_features(path: Path) -> dict:
    """Deserialize the feature dict saved by `save_features`.

    Args:
        path: Input `.parquet` path.

    Returns:
        Feature series dict with keys `t_s`, `kp_speed`, `motion_bg`,
        `motion`, `sharpness`, `subject_visible`, `multi_subject`,
        `subject_bbox` (reconstructed as `(x0, y0, x1, y1)` tuples, or
        `None` where any coordinate was `NaN`). Does not restore
        `features_config_sha256`/`n_tracks` (only used by `save_features`
        for storage metadata, not by downstream consumers of the returned
        dict).
    """
    import pandas as pd

    df = pd.read_parquet(path)
    bbox = [
        None if np.isnan(x0) else (x0, y0, x1, y1)
        for x0, y0, x1, y1 in zip(
            df["bbox_x0"],
            df["bbox_y0"],
            df["bbox_x1"],
            df["bbox_y1"],
            strict=True,
        )
    ]
    return {
        "t_s": df["t_s"].tolist(),
        "kp_speed": df["kp_speed"].tolist(),
        "motion_bg": df["motion_bg"].tolist(),
        "motion": df["motion"].tolist(),
        "sharpness": df["sharpness"].tolist(),
        "subject_visible": df["subject_visible"].tolist(),
        "multi_subject": df["multi_subject"].tolist(),
        "subject_bbox": bbox,
    }
