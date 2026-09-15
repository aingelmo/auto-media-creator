"""6.6 Per-clip effects: Ken Burns, blur-pad params, hook speed ramp, hook text."""

from __future__ import annotations

from PIL import ImageFont

HOOK_TEXT_MAX_W = 1000  # px at 1080 wide; drawtext doesn't wrap or auto-fit


def fit_font_size(text: str, font: str, size: int, max_w: int = HOOK_TEXT_MAX_W) -> int:
    """Largest size <= `size` whose rendered `text` width fits `max_w` (min 40)."""
    # ponytail: no wrapping; the prompt caps the line at 6 words, this only
    # guards long words. Add manual "\n" insertion if lines still overflow.
    while size > 40 and ImageFont.truetype(font, size).getlength(text) > max_w:
        size -= 4
    return size


def effect_for(
    candidate: dict,
    layout: str,
    config: dict,
    ramp: dict | None = None,
    hook_text: tuple[str, int] | None = None,
    role: str | None = None,
    peak_f: int | None = None,
) -> tuple[str, dict]:
    """Pick the effect and its parameters for a clip, per #6.6.

    Args:
        candidate: Candidate dict; reads `kind`.
        layout: Crop layout for this clip, as returned by `compute_crop`
            (`"crop"` or `"blur_pad"`).
        config: Planner config; reads `ken_burns`, `zoom_per_frame`,
            `zoom_max` (for image candidates), `blur_radius`,
            `blur_power`, `bg_brightness` (for `blur_pad` layouts),
            `punch_in`, `punch_frames`, `punch_zoom`, `hook_flash`,
            `flash_frames`.
        ramp: `compute_in_out`'s `ramp` output (`{"speed", "frames",
            "start_f"}`) or `None`.
        hook_text: `(hook_line, d_f)` for the hook slot, or `None`. Ignored
            when `hook_line` is empty or `config["hook_text"]` is off.
        role: Slot role (`"hook"`, `"develop"`, `"close"`), or `None`.
        peak_f: `compute_in_out`'s `peak_f` output, or `None`.

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
        - With `hook_text`, `effect_params` also has `text`, `font`,
          `font_size` (shrunk by `fit_font_size` so the line fits 1000 px
          at 1080 wide), `text_y`, `text_frames`, `fade_frames`; `effect`
          is unchanged (presence of `text` is the render's switch).
        - For `role == "develop"` video clips with `config["punch_in"]`,
          `effect_params` also has `punch_frames`, `punch_zoom`.
        - For `role == "hook"` video clips with `peak_f is not None` and
          `config["hook_flash"]`, `effect_params` also has `flash_frame`
          (`= peak_f`), `flash_frames`.
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
    effect = "none"
    if ramp is not None:
        effect = "ramp"
        params |= {
            "ramp_speed": ramp["speed"],
            "ramp_frames": ramp["frames"],
            "ramp_start_f": ramp["start_f"],
        }
    if hook_text and hook_text[0] and config.get("hook_text", True):
        line, d_f = hook_text
        params |= {
            "text": line,
            "font": config["hook_text_font"],
            "font_size": fit_font_size(
                line, config["hook_text_font"], config["hook_text_size"]
            ),
            "text_y": config["hook_text_y"],
            "text_frames": min(config["hook_text_max_frames"], d_f),
            "fade_frames": config["hook_text_fade_frames"],
        }
    if role == "develop" and config.get("punch_in", True):
        params |= {
            "punch_frames": config["punch_frames"],
            "punch_zoom": config["punch_zoom"],
        }
    if role == "hook" and peak_f is not None and config.get("hook_flash", True):
        params |= {"flash_frame": peak_f, "flash_frames": config["flash_frames"]}
    return effect, params
