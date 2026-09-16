"""Layer 3 - LLM selector (Gemini), #5.

Builds the inline-image request (#5.1) from the admissible candidates in
candidates.json, sends it via google-genai's Interactions API, and applies
retries on `status: "incomplete"` (#5.6). Saves each attempt as
`selection_attempt_N.json` in session_dir. The result (`selection`,
`selection_meta`) is passed straight to `session.run_planner`.
"""

from __future__ import annotations

from edl_agent.selector.hooks import generate_hook_copy
from edl_agent.selector.pipeline import select
from edl_agent.selector.prompts import admissible_candidates, build_parts

__all__ = [
    "admissible_candidates",
    "build_parts",
    "generate_hook_copy",
    "select",
]
