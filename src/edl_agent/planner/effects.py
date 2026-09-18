"""6.6 Per-clip effects: Ken Burns, blur-pad params, hook speed ramp, hook text."""

from __future__ import annotations

from PIL import ImageFont

HOOK_TEXT_MAX_W = 900  # px at 1080 wide; the safe-zone text block width
HOOK_TEXT_MIN_SIZE = 56


def _wrap_two_lines(text: str, font: str, size: int, max_w: int) -> list[str] | None:
    """Best (narrowest-max-line) 2-line split of `text` at a space.

    `None` if `text` is a single word (nothing to split on) or no split
    keeps both lines under `max_w`.
    """
    words = text.split(" ")
    if len(words) < 2:
        return None
    f = ImageFont.truetype(font, size)
    best: list[str] | None = None
    best_width: float | None = None
    for i in range(1, len(words)):
        line1, line2 = " ".join(words[:i]), " ".join(words[i:])
        width = max(f.getlength(line1), f.getlength(line2))
        if width <= max_w and (best_width is None or width < best_width):
            best, best_width = [line1, line2], width
    return best


def layout_hook_line(
    text: str, font: str, size: int, max_w: int = HOOK_TEXT_MAX_W
) -> tuple[str, int]:
    r"""Upper-case `text`, wrap to <= 2 lines, shrinking `size` if needed.

    Returns `(text, font_size)`; `text` joins wrapped lines with a literal
    `\N` (an ASS line break, see `render._common.hook_text_filter`), or is
    a single line if it already fits `max_w`.
    """
    # ponytail: 2 lines max, no 3-line wrap. The prompt caps hook lines at
    # ~48 chars, so a single long unsplittable word is the only case that
    # still clips at HOOK_TEXT_MIN_SIZE; add 3-line wrap if that happens.
    text = text.upper()
    while True:
        f = ImageFont.truetype(font, size)
        if f.getlength(text) <= max_w:
            return text, size
        split = _wrap_two_lines(text, font, size, max_w)
        if split:
            return "\\N".join(split), size
        if size <= HOOK_TEXT_MIN_SIZE:
            split = _wrap_two_lines(text, font, size, max_w=10**9) or [text]
            return "\\N".join(split), size
        size -= 4


def effect_for(
    candidate: dict,
    layout: str,
    config: dict,
    ramp: dict | None = None,
    hook_text: tuple[str, int] | None = None,
    role: str | None = None,
    peak_f: int | None = None,
) -> tuple[str, dict]:
    r"""Pick the effect and its parameters for a clip, per #6.6.

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
        - With `hook_text`, `effect_params` also has `text` (upper-cased,
          wrapped to <= 2 lines by `layout_hook_line`, joined with a literal
          `\\N`), `font`, `font_size` (shrunk to fit `HOOK_TEXT_MAX_W` if
          even 2 lines don't), `text_y` (fraction of height, centre of the
          text block), `text_frames`, `fade_frames`; `effect` is unchanged
          (presence of `text` is the render's switch).
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
        text, font_size = layout_hook_line(
            line, config["hook_text_font"], config["hook_text_size"]
        )
        params |= {
            "text": text,
            "font": config["hook_text_font"],
            "font_size": font_size,
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
