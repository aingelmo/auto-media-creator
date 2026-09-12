"""Normalized crop -> pixels (#6.5).

Pure functions; used by the planner (part 3) and by segments.py to
recompute over the proxy's dimensions.
"""

from __future__ import annotations


def is_916(w: int, h: int) -> bool:
    """Check whether `w:h` is already 9:16 (0.01 tolerance), needing no crop.

    Args:
        w: Width, in pixels.
        h: Height, in pixels.

    Returns:
        `True` if `w / h` is within 0.01 of `9 / 16`.
    """
    return abs(w / h - 9 / 16) < 0.01


def _even(x: float) -> int:
    v = round(x)
    return v - (v % 2)


def crop_to_px(crop: dict, w: int, h: int, layout: str) -> dict:
    """Convert a normalized (0-1) crop rect to even pixel coordinates, per #6.5.

    Args:
        crop: Normalized crop rect `{x, y, w, h}`, all in [0, 1] (as
            returned by `planner.compute_crop`).
        w: Source width, in pixels.
        h: Source height, in pixels.
        layout: `"crop"` or `"blur_pad"` (see `planner.compute_crop`); only
            `"crop"` on a non-9:16 source forces the pixel width to match a
            9:16 aspect ratio derived from the pixel height.

    Returns:
        Pixel crop rect `{x, y, w, h}` (all `int`), even-valued, clamped to
        fit within `w`x`h`.
    """
    h_px = _even(crop["h"] * h)
    if layout == "crop" and not is_916(w, h):
        w_px = _even(h_px * 9 / 16)
        if w_px > w:
            w_px = w if w % 2 == 0 else w - 1
            h_px = _even(w_px * 16 / 9)
    else:
        w_px = _even(crop["w"] * w)
    h_px, w_px = max(h_px, 2), max(w_px, 2)
    x_px = max(0, min(_even(crop["x"] * w), w - w_px))
    y_px = max(0, min(_even(crop["y"] * h), h - h_px))
    return {"x": x_px, "y": y_px, "w": w_px, "h": h_px}
