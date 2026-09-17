"""Session cost-ledger summing, #11."""

from __future__ import annotations

from unittest.mock import patch

from edl_agent.web import state


def test_total_cost_usd_sums_ledger_lines(tmp_path) -> None:
    session_dir = tmp_path / "s1"
    session_dir.mkdir()
    session_dir.joinpath("costs.jsonl").write_text(
        '{"stage": "selection", "cost_usd": 0.01}\n'
        '{"stage": "hooks", "cost_usd": 0.002}\n'
    )

    with patch.object(state, "SESSIONS_DIR", tmp_path):
        assert state.total_cost_usd("s1") == 0.012


def test_total_cost_usd_is_zero_with_no_ledger(tmp_path) -> None:
    session_dir = tmp_path / "s1"
    session_dir.mkdir()

    with patch.object(state, "SESSIONS_DIR", tmp_path):
        assert state.total_cost_usd("s1") == 0.0
