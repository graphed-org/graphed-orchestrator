"""Regression guard for a real failure: a milestone was marked DONE off a CI run for an earlier
commit while the *pinned* commit's CI was still ``in_progress``. The orchestrator must now refuse to
record DONE until the exact commit's CI is confirmed green, and ``in_progress`` must count as
not-green (plan B.3 #4)."""

from __future__ import annotations

from fakers import TOTAL, at_implementing, ev

from graphed_orchestrator import (
    Action,
    CiState,
    GateReport,
    Phase,
    ci_state,
    classify,
    is_ci_green,
    wait_for_ci,
)

LOCAL_GREEN = {
    "frozen_tests": True,
    "coverage": True,
    "lint": True,
    "types": True,
    "determinism": True,
    "integrity_scan": True,
}


def _at_review() -> object:
    o = at_implementing()
    o.record_iteration(ev(0, pass_count=TOTAL))
    assert o.phase == Phase.REVIEW
    return o


# ---- the engine refuses DONE without a confirmed-green CI --------------------
def test_approve_with_ci_in_progress_does_not_reach_done() -> None:
    o = _at_review()
    decision = o.review(approve=True, gates=GateReport(**LOCAL_GREEN, ci=None))  # None == in_progress
    assert decision.action is Action.CONTINUE
    assert "awaiting_ci" in decision.signals
    assert o.phase == Phase.REVIEW  # NOT DONE
    assert o.record.incident is None  # and it is not an integrity incident, just "not ready"


def test_approve_with_failed_ci_does_not_reach_done() -> None:
    o = _at_review()
    decision = o.review(approve=True, gates=GateReport(**LOCAL_GREEN, ci=False))
    assert decision.action is Action.CONTINUE
    assert o.phase == Phase.REVIEW


def test_approve_reaches_done_only_once_ci_is_confirmed_green() -> None:
    o = _at_review()
    # first attempt while CI pending -> held in REVIEW
    o.review(approve=True, gates=GateReport(**LOCAL_GREEN, ci=None))
    assert o.phase == Phase.REVIEW
    # CI completes green for the pinned commit -> NOW it may advance
    decision = o.review(approve=True, gates=GateReport(**LOCAL_GREEN, ci=True))
    assert decision.action is Action.ADVANCE
    assert o.phase == Phase.DONE


def test_red_local_gate_under_approve_is_still_an_integrity_incident() -> None:
    # the CI path must not weaken the anti-rubber-stamp rule: approving on a red LOCAL gate pauses.
    o = _at_review()
    decision = o.review(approve=True, gates=GateReport(**{**LOCAL_GREEN, "coverage": False}, ci=True))
    assert decision.action is Action.PAUSE
    assert decision.incident is True


# ---- ci.py: in_progress / queued / missing are NOT green --------------------
SHA = "abc1234def"


def test_classify_completed_success_is_green() -> None:
    runs = [{"headSha": SHA, "status": "completed", "conclusion": "success"}]
    assert classify(runs, SHA) is CiState.GREEN
    assert is_ci_green("org/repo", SHA, query=lambda _r: runs) is True


def test_classify_in_progress_is_pending_not_green() -> None:
    runs = [{"headSha": SHA, "status": "in_progress", "conclusion": None}]
    assert classify(runs, SHA) is CiState.PENDING
    assert is_ci_green("org/repo", SHA, query=lambda _r: runs) is False


def test_classify_any_incomplete_run_for_sha_is_pending() -> None:
    runs = [
        {"headSha": SHA, "status": "completed", "conclusion": "success"},
        {"headSha": SHA, "status": "queued", "conclusion": None},  # a second job still queued
    ]
    assert classify(runs, SHA) is CiState.PENDING  # must wait for ALL of the commit's runs


def test_classify_failure_is_failed() -> None:
    runs = [{"headSha": SHA, "status": "completed", "conclusion": "failure"}]
    assert classify(runs, SHA) is CiState.FAILED


def test_classify_no_run_for_sha_is_missing() -> None:
    runs = [{"headSha": "9999999", "status": "completed", "conclusion": "success"}]
    assert classify(runs, SHA) is CiState.MISSING
    assert ci_state("org/repo", SHA, query=lambda _r: runs) is CiState.MISSING


def test_classify_matches_short_or_long_sha() -> None:
    runs = [{"headSha": SHA + "00000", "status": "completed", "conclusion": "success"}]
    assert classify(runs, SHA) is CiState.GREEN  # short pin matches full head SHA


def test_wait_for_ci_polls_until_terminal_then_returns_green() -> None:
    # simulate a run that is in_progress for two polls, then completes success
    seq = [
        [{"headSha": SHA, "status": "in_progress", "conclusion": None}],
        [{"headSha": SHA, "status": "in_progress", "conclusion": None}],
        [{"headSha": SHA, "status": "completed", "conclusion": "success"}],
    ]
    calls = {"n": 0}

    def query(_repo: str) -> list[dict[str, object]]:
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return seq[i]

    slept: list[float] = []
    result = wait_for_ci("org/repo", SHA, query=query, poll_s=5.0, sleep=slept.append)
    assert result is CiState.GREEN
    assert calls["n"] == 3  # polled until it actually completed
    assert slept == [5.0, 5.0]  # waited between the two pending polls


def test_wait_for_ci_times_out_pending_without_marking_green() -> None:
    runs = [{"headSha": SHA, "status": "in_progress", "conclusion": None}]
    result = wait_for_ci("org/repo", SHA, query=lambda _r: runs, timeout_s=0.0, sleep=lambda _s: None)
    assert result is CiState.PENDING  # never green on timeout
