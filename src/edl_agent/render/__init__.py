"""Layer 6 (preview) and Layer 7 (render): segments, concat, audio, checks R1-R6.

See docs/architecture/09-preview.md #9, docs/architecture/10-render.md #10.
"""

from __future__ import annotations

from edl_agent.render._common import (
    COLOR_ARGS,
    FINAL_TARGET,
    PREVIEW_TARGET,
    RenderError,
)
from edl_agent.render.checks import (
    CheckResult,
    check_r1_frame_count,
    check_r2_phash,
    check_r3_reel_duration,
    check_r4_color,
    check_r5_loudnorm_linear,
    check_r6_monotonic_dts,
    run_render_checks,
)
from edl_agent.render.concat import concat_and_audio
from edl_agent.render.crop import crop_to_px, is_916
from edl_agent.render.pipeline import run_render
from edl_agent.render.profile import get_render_profile
from edl_agent.render.segments import (
    render_image_segment,
    render_preview_segments,
    render_segment,
    render_segments,
    render_video_segment,
)

__all__ = [
    "COLOR_ARGS",
    "FINAL_TARGET",
    "PREVIEW_TARGET",
    "CheckResult",
    "RenderError",
    "check_r1_frame_count",
    "check_r2_phash",
    "check_r3_reel_duration",
    "check_r4_color",
    "check_r5_loudnorm_linear",
    "check_r6_monotonic_dts",
    "concat_and_audio",
    "crop_to_px",
    "get_render_profile",
    "is_916",
    "render_image_segment",
    "render_preview_segments",
    "render_segment",
    "render_segments",
    "render_video_segment",
    "run_render",
    "run_render_checks",
]
