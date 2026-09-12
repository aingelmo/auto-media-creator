"""6.4 9:16 crop: subject-centered crop rect, with blur-pad fallback."""

from __future__ import annotations

from edl_agent.render import is_916


def compute_crop(
    bbox: tuple[float, float, float, float], w: int, h: int, config: dict
) -> dict:
    """Compute the 9:16 crop centered on the subject bbox, per #6.4.

    Args:
        bbox: `(x0, y0, x1, y1)`, normalized, the subject bbox median over
            `[in_s, out_s]`.
        w: Source width, in pixels.
        h: Source height, in pixels.
        config: Planner config; reads `upscale_threshold` and
            `allow_blur_pad`.

    Returns:
        Dict with keys:
        - `crop` (dict): normalized crop rect `{x, y, w, h}`, all in
          [0, 1].
        - `layout` (str): `"crop"` if the source can be cropped to 9:16
          without excessive upscaling, `"blur_pad"` if it must instead be
          letterboxed over a blurred background (when upscale exceeds
          `config["upscale_threshold"]` and `config["allow_blur_pad"]` is
          set).
        - `subject_cropped` (bool): whether the subject bbox extends
          outside the chosen crop rect (beyond a small tolerance).
        - `warnings` (list[str]): `["upscale_gt_1.3"]` if the crop would
          need more upscaling than `config["upscale_threshold"]`; empty
          otherwise.
    """
    warnings: list[str] = []

    if is_916(w, h):
        return {
            "crop": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
            "layout": "crop",
            "subject_cropped": False,
            "warnings": warnings,
        }

    if w / h > 9 / 16:
        h_n, w_n = 1.0, (9 / 16) * h / w
    else:
        w_n, h_n = 1.0, (16 / 9) * w / h

    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    x = max(0.0, min(cx - w_n / 2, 1 - w_n))
    y = max(0.0, min(cy - h_n / 2, 1 - h_n))

    tol = 0.05
    subject_cropped = (
        bbox[0] < x - tol * w_n
        or bbox[2] > x + w_n + tol * w_n
        or bbox[1] < y - tol * h_n
        or bbox[3] > y + h_n + tol * h_n
    )

    upscale = 1080 / (w_n * w)
    layout = "crop"
    if upscale > config["upscale_threshold"]:
        warnings.append("upscale_gt_1.3")
        if config["allow_blur_pad"]:
            layout = "blur_pad"

    return {
        "crop": {"x": x, "y": y, "w": w_n, "h": h_n},
        "layout": layout,
        "subject_cropped": subject_cropped,
        "warnings": warnings,
    }
