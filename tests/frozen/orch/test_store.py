"""Durable state backing (plan B.4): deterministic, append-only, honest."""

from __future__ import annotations

from pathlib import Path

from fakers import TOTAL, at_implementing, ev

from graphed_orchestrator import GateReport
from graphed_orchestrator.store import append_attempt, is_done, write_state


def test_write_state_is_byte_deterministic(tmp_path: Path) -> None:
    o = at_implementing()
    o.record_iteration(ev(0, pass_count=2))
    p1 = tmp_path / "a" / "state.json"
    p2 = tmp_path / "b" / "state.json"
    write_state(p1, "graphed-orchestrator", [o.record])
    write_state(p2, "graphed-orchestrator", [o.record])
    a, b = p1.read_text(), p2.read_text()

    # identical modulo the timestamp line
    def strip(s: str) -> str:
        return "\n".join(line for line in s.splitlines() if "updated_at" not in line)

    assert strip(a) == strip(b)
    assert '"repo": "graphed-orchestrator"' in a


def test_append_attempt_grows_log(tmp_path: Path) -> None:
    o = at_implementing()
    o.record_iteration(ev(0, pass_count=2))
    log = tmp_path / "M0" / "attempts.md"
    append_attempt(log, o.record, summary="first try")
    o.record_iteration(ev(1, pass_count=3))
    append_attempt(log, o.record, summary="second try")
    text = log.read_text()
    assert "first try" in text and "second try" in text
    assert text.count("## Iteration") == 2


def test_is_done(tmp_path: Path) -> None:
    o = at_implementing()
    o.record_iteration(ev(0, pass_count=TOTAL))
    o.review(
        approve=True,
        gates=GateReport(
            frozen_tests=True,
            coverage=True,
            lint=True,
            types=True,
            determinism=True,
            integrity_scan=True,
            ci=True,
        ),
    )
    assert is_done(o.record) is True
