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


def _confirm_effects_preview(job: JobState) -> None:
    """Wait for, then answer, the render stage's hook-flash/punch-in preview pause."""
    deadline = time.monotonic() + 5
    while job.pause_kind != "effects_preview" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert job.pause_kind == "effects_preview"
    job.effects_preview_again = False
    job.cancelled = False
    job.confirm_event.set()


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

    def fake_run_hooks(
        session_dir, candidates, edl, selection, theme, client, model, **kwargs
    ):
        return {
            "candidate_id": "hook1",
            "hook_line": "la barra despega del suelo",
            "hooks": [
                {"angle": "afirmacion", "hook_line": "la barra despega del suelo"}
            ],
            "dropped": [],
            "evidence": ["barra en el suelo"],
            "rejected": None,
            "source": "llm",
        }

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
        patch("edl_agent.web.stages.ingest.run_ingest", return_value=manifest),
        patch("edl_agent.web.stages.ingest.slots_from_file", return_value=slots),
        patch(
            "edl_agent.web.stages.candidates.yolo_pose_detector", return_value=Mock()
        ),
        patch(
            "edl_agent.web.stages.candidates.run_candidates",
            side_effect=fake_run_candidates,
        ),
        patch("edl_agent.web.stages.planner.run_hooks", side_effect=fake_run_hooks),
        patch("edl_agent.web.stages.planner.run_planner", side_effect=fake_run_planner),
        patch("edl_agent.web.stages.planner.render_hook_previews"),
        patch("edl_agent.web.stages.render.render_preview_segments"),
        patch("edl_agent.web.stages.render.render_segments"),
        patch("edl_agent.web.stages.render.concat_and_audio"),
        patch("edl_agent.web.stages.render.run_render_checks", return_value=[]),
        patch("edl_agent.llm.ollama_client.requests.post", return_value=ollama_reply),
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
        _confirm_effects_preview(job)
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

    def fake_run_hooks(
        session_dir, candidates, edl, selection, theme, client, model, **kwargs
    ):
        return {
            "candidate_id": "c01",
            "hook_line": "la barra despega del suelo",
            "hooks": [
                {"angle": "afirmacion", "hook_line": "la barra despega del suelo"}
            ],
            "dropped": [],
            "evidence": ["barra en el suelo"],
            "rejected": None,
            "source": "llm",
        }

    job = JobState()
    with (
        patch("edl_agent.web.stages.ingest.run_ingest", return_value=manifest),
        patch(
            "edl_agent.web.stages.ingest.slots_from_file", return_value=initial_slots
        ),
        patch(
            "edl_agent.web.stages.candidates.slots_from_file",
            return_value=shortened_slots,
        ),
        patch(
            "edl_agent.web.stages.candidates.yolo_pose_detector", return_value=Mock()
        ),
        patch(
            "edl_agent.web.stages.candidates.run_candidates", return_value=candidates
        ),
        patch("edl_agent.web.stages.candidates.cut_music"),
        patch("edl_agent.web.stages.candidates.sha256_file", return_value="new"),
        patch(
            "edl_agent.web.stages.selection.run_selection",
            return_value=({"selected": [], "rejected": [], "notes": ""}, {}),
        ),
        patch("edl_agent.web.stages.planner.run_hooks", side_effect=fake_run_hooks),
        patch("edl_agent.web.stages.planner.run_planner", side_effect=fake_run_planner),
        patch("edl_agent.web.stages.planner.render_hook_previews"),
        patch("edl_agent.web.stages.render.render_preview_segments"),
        patch("edl_agent.web.stages.render.render_segments"),
        patch("edl_agent.web.stages.render.concat_and_audio"),
        patch("edl_agent.web.stages.render.run_render_checks", return_value=[]),
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
        _confirm_effects_preview(job)
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


def _run_job_to_hook_choice(
    tmp_path,
    hook_choice_b: str,
    hook_line_override: str = "",
    hook_flash: bool = True,
    brief: str = "",
    audience: str = "prospects",
) -> tuple[JobState, Mock, list[dict], list[dict], Mock]:
    """Drive a job to the hook-choice pause (image-only sources skip both
    pauses), answer it with `hook_choice_b`, then run it to completion with
    every render/planner call mocked. Returns the job and the `render_segments`
    mock so callers can inspect suffix/reuse kwargs used for variant B.
    """
    session_dir = tmp_path
    manifest = {
        "session_id": "s1",
        "sources": [{"src": "inputs/a.png", "type": "image"}],
        "target": {},
        "music": None,
    }
    slots = {"slots": [{"slot": 0, "start_f": 0, "end_f": 30, "role": "hook"}]}
    candidates = {"candidates": []}
    edl = {"clips": [{"slot": 0, "role": "hook", "effect_params": {}}]}

    planner_calls: list[dict] = []
    call_order: list[str] = []

    def fake_run_planner(
        session_dir, manifest, candidates, slots, selection, meta, **kw
    ):
        planner_calls.append(kw)
        call_order.append("planner")
        return edl

    hooks_calls = []

    def fake_run_hooks(
        session_dir, candidates, edl, selection, theme, client, model, **kwargs
    ):
        hooks_calls.append(kwargs)
        call_order.append("hooks")
        return {
            "candidate_id": "c01",
            "hook_line": "la barra despega del suelo",
            "hooks": [
                {"angle": "pregunta", "hook_line": "el jueves de hyrox"},
                {"angle": "afirmacion", "hook_line": "la barra despega del suelo"},
                {"angle": "contraste", "hook_line": "cinco estaciones seguidas"},
            ],
            "dropped": [],
            "evidence": ["barra en el suelo"],
            "rejected": None,
            "source": "llm",
        }

    render_segments_mock = Mock()
    render_hook_previews_mock = Mock()
    job = JobState()
    # render_segments/run_planner are shared mocks patched into both the
    # `render` stage (variant A) and `variant_b` stage (variant B), which
    # import them independently -- see AGENTS.md's note on module splits.
    with (
        patch("edl_agent.web.stages.ingest.run_ingest", return_value=manifest),
        patch("edl_agent.web.stages.ingest.slots_from_file", return_value=slots),
        patch(
            "edl_agent.web.stages.candidates.yolo_pose_detector", return_value=Mock()
        ),
        patch(
            "edl_agent.web.stages.candidates.run_candidates", return_value=candidates
        ),
        patch(
            "edl_agent.web.stages.selection.run_selection",
            return_value=({"selected": [], "rejected": [], "notes": ""}, {}),
        ),
        patch("edl_agent.web.stages.planner.run_hooks", side_effect=fake_run_hooks),
        patch("edl_agent.web.stages.planner.run_planner", side_effect=fake_run_planner),
        patch(
            "edl_agent.web.stages.variant_b.run_planner", side_effect=fake_run_planner
        ),
        patch(
            "edl_agent.web.stages.planner.render_hook_previews",
            render_hook_previews_mock,
        ),
        patch("edl_agent.web.stages.render.render_preview_segments"),
        patch("edl_agent.web.stages.variant_b.render_preview_segments"),
        patch("edl_agent.web.stages.render.render_segments", render_segments_mock),
        patch("edl_agent.web.stages.variant_b.render_segments", render_segments_mock),
        patch("edl_agent.web.stages.render.concat_and_audio"),
        patch("edl_agent.web.stages.variant_b.concat_and_audio"),
        patch("edl_agent.web.stages.render.run_render_checks", return_value=[]),
        patch("edl_agent.web.stages.variant_b.run_render_checks", return_value=[]),
    ):
        thread = threading.Thread(
            target=run_pipeline_job,
            args=(
                session_dir,
                "ollama",
                "qwen3-vl:8b-instruct",
                job,
                False,
                "training",
                hook_line_override,
                brief,
                audience,
            ),
        )
        thread.start()

        deadline = time.monotonic() + 5
        while job.pause_kind != "hook_choice" and time.monotonic() < deadline:
            time.sleep(0.01)
        assert job.pause_kind == "hook_choice"
        job.hook_choice = ""
        job.hook_choice_b = hook_choice_b
        job.hook_flash = hook_flash
        job.more_hooks = False
        job.cancelled = False
        job.confirm_event.set()
        _confirm_effects_preview(job)
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert job.error is None
    assert job.done
    # run_planner builds a hookless preview EDL before the manual-only
    # hooks stage; with no override the web path never calls run_hooks.
    assert call_order[0] == "planner"
    if hook_line_override:
        assert call_order[:2] == ["planner", "hooks"]
    else:
        assert "hooks" not in call_order
    return (
        job,
        render_segments_mock,
        hooks_calls,
        planner_calls,
        render_hook_previews_mock,
    )


def test_hook_choice_b_renders_variant_b_reel(tmp_path) -> None:
    job, render_segments_mock, _hooks_calls, _planner_calls, _hp = (
        _run_job_to_hook_choice(tmp_path, "line b")
    )

    calls = render_segments_mock.call_args_list
    assert len(calls) == 2  # variant A, then variant B
    assert calls[1].kwargs["suffix"] == "_b"
    assert job.check_results_b == []


def test_no_hook_choice_b_skips_variant_b_render(tmp_path) -> None:
    job, render_segments_mock, _hooks_calls, _planner_calls, _hp = (
        _run_job_to_hook_choice(tmp_path, "")
    )

    calls = render_segments_mock.call_args_list
    assert len(calls) == 1  # variant A only
    assert job.check_results_b == []


def test_job_hook_line_override_is_passed_to_run_hooks(tmp_path) -> None:
    _job, _rsm, hooks_calls, _pc, _hp = _run_job_to_hook_choice(
        tmp_path, "", hook_line_override="Del operador"
    )

    assert hooks_calls == [
        {
            "hook_line_override": "Del operador",
            "brief": "",
            "audience": "prospects",
        }
    ]


def test_job_brief_and_audience_are_passed_to_run_hooks(tmp_path) -> None:
    _job, _rsm, hooks_calls, _pc, _hp = _run_job_to_hook_choice(
        tmp_path,
        "",
        hook_line_override="Del operador",
        brief="Clase de Hyrox del jueves",
        audience="members",
    )

    assert hooks_calls == [
        {
            "hook_line_override": "Del operador",
            "brief": "Clase de Hyrox del jueves",
            "audience": "members",
        }
    ]


def test_manual_hooks_stage_writes_zero_cost_hooks_json(tmp_path) -> None:
    import json as _json

    _job, _rsm, hooks_calls, _pc, _hp = _run_job_to_hook_choice(
        tmp_path, "", brief="Clase de Hyrox del jueves", audience="members"
    )

    assert hooks_calls == []
    on_disk = _json.loads((tmp_path / "hooks.json").read_text())
    assert on_disk["hooks"] == []
    assert on_disk["source"] == "manual"
    assert on_disk["cost_usd"] == 0.0
    assert on_disk["brief"] == "Clase de Hyrox del jueves"
    assert on_disk["audience"] == "members"


def test_job_hook_flash_is_passed_to_run_planner(tmp_path) -> None:
    _job, _rsm, _hooks_calls, planner_calls, _hp = _run_job_to_hook_choice(
        tmp_path, "", hook_flash=False
    )

    assert planner_calls[-1]["config"]["hook_flash"] is False


def test_render_hook_previews_receives_no_llm_lines(tmp_path) -> None:
    _job, _rsm, _hooks_calls, _pc, render_hook_previews_mock = _run_job_to_hook_choice(
        tmp_path, ""
    )

    lines = render_hook_previews_mock.call_args_list[0].args[3]
    assert lines == []


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


def test_clear_stage_artifacts_does_not_touch_cost_ledger(tmp_path) -> None:
    """A regenerate clears selection.json/hooks.json but must never clear
    costs.jsonl, or the lifetime cost total would reset on every regenerate."""
    (tmp_path / "selection.json").write_text("{}")
    (tmp_path / "costs.jsonl").write_text('{"stage": "selection", "cost_usd": 0.01}\n')

    clear_stage_artifacts(tmp_path, "selection")

    assert not (tmp_path / "selection.json").exists()
    assert (tmp_path / "costs.jsonl").exists()


def test_render_stage_caches_effects_preview_combos_and_reuses_clips(tmp_path) -> None:
    """Revisiting an already-rendered hook_flash/punch_in combo skips
    re-encoding; a fresh combo hardlinks the clips the toggle didn't touch."""
    from edl_agent.web.stages.render import _run_render_stage

    session_dir = tmp_path
    manifest = {"sources": []}

    def fake_build_final_edl(
        session_dir, manifest, candidates, slots, selection, meta, job
    ):
        return {
            "clips": [
                {"slot": 0, "role": "hook", "effect_params": {}},
                {
                    "slot": 1,
                    "role": "develop",
                    "effect_params": {"punch_zoom": 1.06} if job.punch_in else {},
                },
            ]
        }

    render_calls: list[tuple[str, dict | None]] = []

    def fake_render_preview_segments(
        edl, manifest, session_dir, suffix="", reuse=None, **kw
    ):
        render_calls.append((suffix, reuse))
        for c in edl["clips"]:
            out = session_dir / f"preview_segments{suffix}" / f"seg_{c['slot']:02d}.mp4"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"x")

    def fake_concat_and_audio(edl, session_dir, threads, preview=False, suffix=""):
        name = f"reel_preview{suffix}.mp4" if preview else f"reel{suffix}.mp4"
        (session_dir / name).write_bytes(b"x")

    job = JobState()
    edl = fake_build_final_edl(session_dir, manifest, {}, {}, None, {}, job)
    with (
        patch(
            "edl_agent.web.stages.render.render_preview_segments",
            fake_render_preview_segments,
        ),
        patch("edl_agent.web.stages.render.concat_and_audio", fake_concat_and_audio),
        patch("edl_agent.web.stages.render.render_segments"),
        patch("edl_agent.web.stages.render.run_render_checks", return_value=[]),
        patch("edl_agent.web.stages.render._build_final_edl", fake_build_final_edl),
    ):
        thread = threading.Thread(
            target=_run_render_stage,
            args=(session_dir, job, False, edl, manifest, {}, {}, None, {}, ""),
        )
        thread.start()

        def _confirm(again: bool, punch_in: bool) -> None:
            deadline = time.monotonic() + 5
            while job.pause_kind != "effects_preview" and time.monotonic() < deadline:
                time.sleep(0.01)
            assert job.pause_kind == "effects_preview"
            # Reset so the next _confirm()'s wait loop doesn't see this same
            # (not-yet-cleared) pause and fire before the next pause happens.
            job.pause_kind = ""
            job.punch_in = punch_in
            job.effects_preview_again = again
            job.cancelled = False
            job.confirm_event.set()

        _confirm(True, True)  # new combo: punch_in on
        _confirm(True, False)  # back to the original combo: cached, no render
        _confirm(False, False)  # proceed to the final render
        thread.join(timeout=5)

    assert not thread.is_alive()
    assert [suffix for suffix, _ in render_calls] == ["_h0p0", "_h0p1"]
    # The second render (new combo) reuses the unaffected hook clip (slot 0)
    # from the first combo's segments, and only re-renders the develop clip.
    _, second_reuse = render_calls[1]
    assert second_reuse is not None
    assert set(second_reuse) == {0}
