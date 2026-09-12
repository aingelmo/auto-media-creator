"""6.6 Per-clip effects: Ken Burns for images, blur-pad params for letterboxing."""

from __future__ import annotations


def effect_for(candidate: dict, layout: str, config: dict) -> tuple[str, dict]:
    """Pick the effect and its parameters for a clip, per #6.6.

    Args:
        candidate: Candidate dict; reads `kind`.
        layout: Crop layout for this clip, as returned by `compute_crop`
            (`"crop"` or `"blur_pad"`).
        config: Planner config; reads `ken_burns`, `zoom_per_frame`,
            `zoom_max` (for image candidates), and `blur_radius`,
            `blur_power`, `bg_brightness` (for `blur_pad` layouts).

    Returns:
        `(effect, effect_params)`:
        - `("kenburns", {"zoom_per_frame": ..., "zoom_max": ...})` for
          image candidates when `config["ken_burns"]` is enabled.
        - `("none", {"blur_radius": ..., "blur_power": ...,
          "bg_brightness": ...})` for `blur_pad` layouts.
        - `("none", {})` otherwise.
    """
    if candidate["kind"] == "image" and config.get("ken_burns", True):
        return "kenburns", {
            "zoom_per_frame": config["zoom_per_frame"],
            "zoom_max": config["zoom_max"],
        }
    if layout == "blur_pad":
        return "none", {
            "blur_radius": config["blur_radius"],
            "blur_power": config["blur_power"],
            "bg_brightness": config["bg_brightness"],
        }
    return "none", {}
