"""Per-line hook preview renders, for the web UI's hook-choice pause, #5.7."""

from __future__ import annotations

from pathlib import Path

from edl_agent.planner._common import DEFAULT_CONFIG
from edl_agent.planner.effects import layout_hook_line
from edl_agent.render.segments import render_segment


def render_hook_previews(
    edl: dict,
    manifest: dict,
    session_dir: Path,
    lines: list[str],
    threads: int,
    tonemap_chain: str,
) -> dict[str, Path]:
    """Render the hook clip once per candidate line (plus a text-less one), per #5.7.

    `edl` is the hookless preview build (`hook_line_override=""`), so the
    hook clip's `effect_params` carries no text params at all; defaults come
    from `DEFAULT_CONFIG` here instead, mirroring `planner.effects`'s own
    `hook_text` branch. `font_size` is recomputed per line so each one fits
    the text box. The white flash is stripped here regardless of
    `DEFAULT_CONFIG["hook_flash"]`: it's a separate on/off decision made
    later at the render stage's `"effects_preview"` pause, not part of this
    hook-line comparison.

    Args:
        edl: EDL dict, as returned by `edl.build_edl`. Reads `clips`
            (looks up the `role == "hook"` clip), `brand`.
        manifest: Manifest dict. Reads `sources`.
        session_dir: Session root directory.
        lines: Candidate hook lines to preview.
        threads: ffmpeg thread count.
        tonemap_chain: HDR (HLG/DV84) tonemap filter chain.

    Returns:
        Mapping `key -> rendered segment path` under
        `session_dir/"hook_previews"/key/`, with `key == "none"` for the
        text-less variant and `key == str(i)` (0-based) for `lines[i]`.
    """
    session_dir = Path(session_dir)
    sources_by_src = {s["src"]: s for s in manifest["sources"]}
    hook_clip = next(c for c in edl["clips"] if c["role"] == "hook")
    font = hook_clip["effect_params"].get("font", DEFAULT_CONFIG["hook_text_font"])

    variants: dict[str, str | None] = {"none": None}
    variants.update({str(i): line for i, line in enumerate(lines)})

    out_dir_base = session_dir / "hook_previews"
    paths: dict[str, Path] = {}
    for key, text in variants.items():
        params = dict(hook_clip["effect_params"])
        params.pop("text", None)
        params.pop("flash_frame", None)
        params.pop("flash_frames", None)
        if text is not None:
            line_text, font_size = layout_hook_line(
                text, font, int(DEFAULT_CONFIG["hook_text_size"])
            )
            params.update(
                {
                    "text": line_text,
                    "font": font,
                    "font_size": font_size,
                    "text_y": DEFAULT_CONFIG["hook_text_y"],
                    "text_frames": min(
                        int(DEFAULT_CONFIG["hook_text_max_frames"]),
                        hook_clip["n_frames"],
                    ),
                    "fade_frames": DEFAULT_CONFIG["hook_text_fade_frames"],
                }
            )
        clip = {**hook_clip, "effect_params": params}
        paths[key] = render_segment(
            clip,
            sources_by_src,
            session_dir,
            out_dir_base / key,
            threads,
            tonemap_chain,
            preview=True,
            brand=edl.get("brand"),
        )
    return paths
