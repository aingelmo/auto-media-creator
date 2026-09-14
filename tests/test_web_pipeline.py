"""Web pipeline: excluding unverified proxies at the confirmation pause."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import Mock, patch

from edl_agent.web.pipeline import JobState, run_pipeline_job


def _fake_ollama_response(json_data):
    resp = Mock()
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def test_excluding_unverified_source_drops_it_before_candidates_using_ollama(
    tmp_path,
) -> None:
    """A clip excluded at the confirmation pause never reaches `run_candidates`,
    and the rest of the pipeline (through the real Ollama client) still completes.
    """
    session_dir = tmp_path
    manifest = {
        "session_id": "s1",
        "sources": [
            {"src": "inputs/good.mov", "type": "video", "proxy_verified": True},
            {"src": "inputs/bad.mov", "type": "video", "proxy_verified": False},
        ],
        "target": {},
        "music": None,
    }
    slots = {"slots": [], "duration_f": 150}
    candidates_seen = {}

    def fake_run_candidates(session_dir, manifest, slots, detector, **kwargs):
        candidates_seen["manifest"] = manifest
        return {"candidates": []}

    def fake_run_planner(session_dir, manifest, candidates, slots, selection, meta, **kw):
        return {"clips": []}

    ollama_reply = _fake_ollama_response(
        {
            "message": {
                "content": json.dumps({"selected": [], "rejected": [], "notes": ""})
            },
            "prompt_eval_count": 10,
            "eval_count": 5,
            "done_reason": "stop",
        }
    )

    job = JobState()
    with (
        patch("edl_agent.web.pipeline.run_ingest", return_value=manifest),
        patch("edl_agent.web.pipeline.slots_from_file", return_value=slots),
        patch("edl_agent.web.pipeline.yolo_pose_detector", return_value=Mock()),
        patch(
            "edl_agent.web.pipeline.run_candidates", side_effect=fake_run_candidates
        ),
        patch("edl_agent.web.pipeline.run_planner", side_effect=fake_run_planner),
        patch("edl_agent.web.pipeline.render_preview_segments"),
        patch("edl_agent.web.pipeline.render_segments"),
        patch("edl_agent.web.pipeline.concat_and_audio"),
        patch("edl_agent.web.pipeline.run_render_checks", return_value=[]),
        patch(
            "edl_agent.llm.ollama_client.requests.post", return_value=ollama_reply
        ),
    ):
        thread = threading.Thread(
            target=run_pipeline_job,
            args=(session_dir, "ollama", "qwen3-vl:8b-instruct", job),
        )
        thread.start()

        # ingest flags the mismatched clip and pauses for confirmation.
        deadline = time.monotonic() + 5
        while not job.awaiting_confirmation and time.monotonic() < deadline:
            time.sleep(0.01)
        assert job.awaiting_confirmation
        assert job.unverified_sources == ["inputs/bad.mov"]

        # Simulate the user excluding the bad clip and continuing.
        job.excluded_sources = ["inputs/bad.mov"]
        job.cancelled = False
        job.confirm_event.set()
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert job.error is None
    assert job.done
    assert [s["src"] for s in candidates_seen["manifest"]["sources"]] == [
        "inputs/good.mov"
    ]
    on_disk = json.loads((session_dir / "manifest.json").read_text())
    assert [s["src"] for s in on_disk["sources"]] == ["inputs/good.mov"]
    selection = json.loads((session_dir / "selection.json").read_text())
    assert selection == {"selected": [], "rejected": [], "notes": ""}
