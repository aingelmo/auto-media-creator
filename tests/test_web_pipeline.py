"""Web pipeline: excluding unverified proxies at the confirmation pause."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import Mock, patch

from edl_agent.web.pipeline import JobState, clear_stage_artifacts, run_pipeline_job


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

    def fake_run_planner(
        session_dir, manifest, candidates, slots, selection, meta, **kw
    ):
        return {"clips": [{"slot": 0, "role": "hook", "effect_params": {}}]}

    def fake_run_hooks(session_dir, candidates, slots, selection, theme, client, model):
        return {"lines": [{"angle": "reto", "text": "vamos"}]}

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
        patch("edl_agent.web.pipeline.run_hooks", side_effect=fake_run_hooks),
        patch("edl_agent.web.pipeline.run_planner", side_effect=fake_run_planner),
        patch("edl_agent.web.pipeline.render_hook_previews"),
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

        # hooks stage pauses for the hook-choice screen next.
        deadline = time.monotonic() + 5
        while job.pause_kind != "hook_choice" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert job.pause_kind == "hook_choice"
        job.hook_choice = ""
        job.more_hooks = False
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


def test_shortening_at_low_candidates_pause_recuts_music_and_readmits_candidates(
    tmp_path,
) -> None:
    """One source clip for 3 slots pauses the job; choosing "shorten" re-cuts the
    music to the suggested duration and recomputes each candidate's `admits_slots`
    against the new, shorter slot list.
    """
    session_dir = tmp_path
    manifest = {
        "session_id": "s1",
        "sources": [{"src": "inputs/a.mov", "type": "video", "proxy_verified": True}],
        "target": {},
        "music": {
            "src": "music/track.mp3",
            "offset_s": 0.0,
            "max_duration_s": 15.0,
            "cut": "music/track_cut.wav",
            "cut_sha256": "orig",
        },
    }
    initial_slots = {
        "slots": [
            {"slot": 0, "start_f": 0, "end_f": 60, "role": "hook"},
            {"slot": 1, "start_f": 60, "end_f": 120, "role": "develop"},
            {"slot": 2, "start_f": 120, "end_f": 180, "role": "close"},
        ],
        "duration_f": 180,
    }
    # 1 slot needing 2.0s; the candidate's 2.2s window still admits it.
    shortened_slots = {
        "slots": [{"slot": 0, "start_f": 0, "end_f": 60, "role": "hook"}],
        "duration_f": 60,
    }
    candidates = {
        "candidates": [
            {
                "id": "c01",
                "src": "inputs/a.mov",
                "kind": "peak",
                "t_peak": 1.0,
                "window": [0.0, 2.2],
                "admits_slots": [0, 1, 2],
            }
        ]
    }

    def fake_run_planner(
        session_dir, manifest, candidates, slots, selection, meta, **kw
    ):
        return {"clips": [{"slot": 0, "role": "hook", "effect_params": {}}]}

    def fake_run_hooks(session_dir, candidates, slots, selection, theme, client, model):
        return {"lines": [{"angle": "reto", "text": "vamos"}]}

    job = JobState()
    with (
        patch("edl_agent.web.pipeline.run_ingest", return_value=manifest),
        patch(
            "edl_agent.web.pipeline.slots_from_file",
            side_effect=[initial_slots, shortened_slots],
        ),
        patch("edl_agent.web.pipeline.yolo_pose_detector", return_value=Mock()),
        patch("edl_agent.web.pipeline.run_candidates", return_value=candidates),
        patch("edl_agent.web.pipeline.cut_music"),
        patch("edl_agent.web.pipeline.sha256_file", return_value="new"),
        patch(
            "edl_agent.web.pipeline.run_selection",
            return_value=({"selected": [], "rejected": [], "notes": ""}, {}),
        ),
        patch("edl_agent.web.pipeline.run_hooks", side_effect=fake_run_hooks),
        patch("edl_agent.web.pipeline.run_planner", side_effect=fake_run_planner),
        patch("edl_agent.web.pipeline.render_hook_previews"),
        patch("edl_agent.web.pipeline.render_preview_segments"),
        patch("edl_agent.web.pipeline.render_segments"),
        patch("edl_agent.web.pipeline.concat_and_audio"),
        patch("edl_agent.web.pipeline.run_render_checks", return_value=[]),
    ):
        thread = threading.Thread(
            target=run_pipeline_job,
            args=(session_dir, "ollama", "qwen3-vl:8b-instruct", job),
        )
        thread.start()

        deadline = time.monotonic() + 5
        while not job.awaiting_confirmation and time.monotonic() < deadline:
            time.sleep(0.01)
        assert job.awaiting_confirmation
        assert job.pause_kind == "low_candidates"
        assert job.low_candidates == {
            "real_sources": 1,
            "slot_count": 3,
            "suggested_duration_s": 5.0,
        }

        job.shorten = True
        job.cancelled = False
        job.confirm_event.set()

        deadline = time.monotonic() + 5
        while job.pause_kind != "hook_choice" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert job.pause_kind == "hook_choice"
        job.hook_choice = ""
        job.more_hooks = False
        job.cancelled = False
        job.confirm_event.set()
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert job.error is None
    assert job.done

    on_disk_slots = json.loads((session_dir / "slots.json").read_text())
    assert on_disk_slots == shortened_slots
    on_disk_manifest = json.loads((session_dir / "manifest.json").read_text())
    assert on_disk_manifest["music"]["max_duration_s"] == 5.0
    on_disk_candidates = json.loads((session_dir / "candidates.json").read_text())
    assert on_disk_candidates["candidates"][0]["admits_slots"] == [0]


def test_clear_stage_artifacts_from_selection_keeps_earlier_stages_and_backs_up_reel(
    tmp_path,
) -> None:
    """Clearing from "selection" removes selection/planner/render outputs but
    leaves ingest/candidates outputs untouched, and backs up the old reel."""
    (tmp_path / "manifest.json").write_text("{}")
    (tmp_path / "candidates.json").write_text("{}")
    (tmp_path / "selection.json").write_text("{}")
    (tmp_path / "selection_meta.json").write_text("{}")
    (tmp_path / "edl.json").write_text("{}")
    (tmp_path / "reel.mp4").write_text("old reel")
    (tmp_path / "segments").mkdir()
    (tmp_path / "segments" / "s0.mp4").write_text("seg")

    clear_stage_artifacts(tmp_path, "selection")

    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "candidates.json").exists()
    assert not (tmp_path / "selection.json").exists()
    assert not (tmp_path / "selection_meta.json").exists()
    assert not (tmp_path / "edl.json").exists()
    assert not (tmp_path / "reel.mp4").exists()
    assert not (tmp_path / "segments").exists()
    assert (tmp_path / "reel.prev.mp4").read_text() == "old reel"
