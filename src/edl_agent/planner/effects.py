"""6.6 Per-clip effects: Ken Burns for images, blur-pad params, hook speed ramp."""

from __future__ import annotations


def effect_for(
    candidate: dict, layout: str, config: dict, ramp: dict | None = None
) -> tuple[str, dict]:
    """Pick the effect and its parameters for a clip, per #6.6.

    Args:
        candidate: Candidate dict; reads `kind`.
        layout: Crop layout for this clip, as returned by `compute_crop`
            (`"crop"` or `"blur_pad"`).
        config: Planner config; reads `ken_burns`, `zoom_per_frame`,
            `zoom_max` (for image candidates), and `blur_radius`,
            `blur_power`, `bg_brightness` (for `blur_pad` layouts).
        ramp: `compute_in_out`'s `ramp` output (`{"speed", "frames",
            "start_f"}`) or `None`.

    Returns:
        `(effect, effect_params)`:
        - `("kenburns", {"zoom_per_frame": ..., "zoom_max": ...})` for
          image candidates when `config["ken_burns"]` is enabled.
        - `("none", {"blur_radius": ..., "blur_power": ...,
          "bg_brightness": ...})` for `blur_pad` layouts.
        - `("none", {})` otherwise.
        - With `ramp`, `effect` is `"ramp"` and `effect_params` also has
          `ramp_speed`, `ramp_frames`, `ramp_start_f` (merged over the
          `blur_pad` params if any). Ramps never apply to images.
    """
    if candidate["kind"] == "image" and config.get("ken_burns", True):
        return "kenburns", {
            "zoom_per_frame": config["zoom_per_frame"],
            "zoom_max": config["zoom_max"],
        }
    params: dict = {}
    if layout == "blur_pad":
        params = {
            "blur_radius": config["blur_radius"],
            "blur_power": config["blur_power"],
            "bg_brightness": config["bg_brightness"],
        }
    if ramp is None:
        return "none", params
    return "ramp", {
        **params,
        "ramp_speed": ramp["speed"],
        "ramp_frames": ramp["frames"],
        "ramp_start_f": ramp["start_f"],
    }
