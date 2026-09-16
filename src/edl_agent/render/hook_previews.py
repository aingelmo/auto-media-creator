"""Per-line hook preview renders, for the web UI's hook-choice pause, #5.7."""

from __future__ import annotations

from pathlib import Path

from edl_agent.planner._common import DEFAULT_CONFIG
from edl_agent.planner.effects import fit_font_size
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

    The EDL's hook clip must already carry text params (the planner having
    run with line #1) for its `font` to be known; `font_size` is
    recomputed per line so each one fits the text box.

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
        text-less variant, `key == str(i)` (0-based) for `lines[i]`, and a
        flash-less twin of each under `f"{key}_noflash"`.
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
        if text is None:
            params.pop("text", None)
        else:
            params["text"] = text
            params["font_size"] = fit_font_size(
                text, font, int(DEFAULT_CONFIG["hook_text_size"])
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

        noflash_params = dict(params)
        noflash_params.pop("flash_frame", None)
        noflash_params.pop("flash_frames", None)
        noflash_clip = {**hook_clip, "effect_params": noflash_params}
        noflash_key = f"{key}_noflash"
        paths[noflash_key] = render_segment(
            noflash_clip,
            sources_by_src,
            session_dir,
            out_dir_base / noflash_key,
            threads,
            tonemap_chain,
            preview=True,
            brand=edl.get("brand"),
        )
    return paths
