import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from calibrate_prompts import build_session_summary, upsert_rating


def _write(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj))


def test_build_session_summary_no_video_returns_none(tmp_path):
    session = tmp_path / "sess"
    session.mkdir()
    assert build_session_summary(session) is None


def test_build_session_summary_prefers_prev_and_parses_json(tmp_path):
    session = tmp_path / "sess"
    session.mkdir()
    (session / "reel.mp4").write_bytes(b"a")
    (session / "reel.prev.mp4").write_bytes(b"b")
    _write(
        session / "hooks.json",
        {"hook_line": "Hola", "hooks": [{"angle": "x", "hook_line": "Hola"}], "dropped": []},
    )

    summary = build_session_summary(session)

    assert summary["video"] == "reel.prev.mp4"
    assert summary["hook"]["line"] == "Hola"
    assert summary["hook"]["alternates"] == [{"angle": "x", "hook_line": "Hola"}]


def test_build_session_summary_missing_json_is_none_not_error(tmp_path):
    session = tmp_path / "sess"
    session.mkdir()
    (session / "reel.mp4").write_bytes(b"a")

    summary = build_session_summary(session)

    assert summary["hook"] is None


def test_upsert_rating_persists_per_hook_line(tmp_path):
    path = tmp_path / "ratings.json"

    hooks = [
        {"angle": "pregunta", "hook_line": "Empieza corriendo y acaba remando", "good": True, "note": "grounded"},
        {"angle": "contraste", "hook_line": "Arranca y acaba igual", "good": False, "note": "template collapse"},
    ]
    ratings = upsert_rating(path, "sess1", hooks)

    assert ratings["sess1"]["hooks"] == hooks
    on_disk = json.loads(path.read_text())
    assert on_disk["sess1"]["hooks"][1]["good"] is False


def test_upsert_rating_overwrites_previous_round(tmp_path):
    path = tmp_path / "ratings.json"

    upsert_rating(path, "sess1", [{"angle": "tu", "hook_line": "a", "good": True, "note": ""}])
    ratings = upsert_rating(path, "sess1", [{"angle": "tu", "hook_line": "b", "good": False, "note": "worse"}])

    assert ratings["sess1"]["hooks"] == [
        {"angle": "tu", "hook_line": "b", "good": False, "note": "worse"}
    ]
