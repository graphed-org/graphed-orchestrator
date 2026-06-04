"""Phase transitions and guards (plan B.1)."""

from __future__ import annotations

import pytest
from fakers import TOTAL, at_implementing, ev

from graphed_orchestrator import Action, GateReport, Orchestrator, Phase, PhaseError, SanityReport
from graphed_orchestrator.gates import evaluate_test_sanity

GREEN = GateReport(
    frozen_tests=True, coverage=True, lint=True, types=True, determinism=True, integrity_scan=True
)
RED = GateReport(
    frozen_tests=True, coverage=False, lint=True, types=True, determinism=True, integrity_scan=True
)


def test_happy_path_pending_to_done() -> None:
    o = at_implementing()
    assert o.phase == Phase.IMPLEMENTING
    assert o.record.freeze_tag == "freeze-Mtest-0"
    o.record_iteration(ev(0, pass_count=TOTAL))
    assert o.phase == Phase.REVIEW
    o.review(approve=True, gates=GREEN)
    assert o.phase == Phase.DONE


def test_failed_sanity_routes_back_to_test_authoring() -> None:
    o = Orchestrator("Mx")
    o.start()
    o.begin_test_authoring()
    bad: SanityReport = evaluate_test_sanity(
        collects=True,
        stub_pass_count=5,
        stub_total=5,
        stub_run1_fail_hash="a",
        stub_run2_fail_hash="a",
        coverage_instrumented=True,
    )
    d = o.run_test_sanity(bad)
    assert d.action == Action.RETRY_L0
    assert o.phase == Phase.TEST_AUTHORING


def test_invalid_transitions_raise() -> None:
    o = Orchestrator("Mx")
    with pytest.raises(PhaseError):
        o.record_iteration(ev(0, pass_count=1))
    with pytest.raises(PhaseError):
        o.freeze("nope")
    o.start()
    with pytest.raises(PhaseError):
        o.review(approve=True, gates=GREEN)  # review requires REVIEW phase


def test_reviewer_approve_on_red_gates_is_an_incident() -> None:
    o = at_implementing()
    o.record_iteration(ev(0, pass_count=TOTAL))
    d = o.review(approve=True, gates=RED)
    assert d.action == Action.PAUSE
    assert d.incident is True
    assert o.phase == Phase.PAUSED


def test_review_rejects_climb_to_escalation() -> None:
    o = at_implementing()
    for _ in range(3):
        o.record_iteration(ev(0, pass_count=TOTAL))
        d = o.review(approve=False, gates=RED, issue_count=4)
        assert o.phase in (Phase.IMPLEMENTING, Phase.PAUSED)
    assert d.signals == ("review_non_convergence",) or o.record.reject_count >= 3


def test_resume_and_abort_are_human_only_paths() -> None:
    o = at_implementing()
    o.record_iteration(ev(0, pass_count=TOTAL, touched=True))
    assert o.phase == Phase.PAUSED
    o.resume()
    assert o.phase == Phase.IMPLEMENTING
    o.record_iteration(ev(1, pass_count=2, tree="z"))
    o.abort()
    assert o.phase == Phase.ABORTED


def test_dispute_correction_refreezes() -> None:
    o = at_implementing()
    o.record_iteration(ev(0, pass_count=3, dispute="T1"))
    assert o.phase == Phase.TEST_DISPUTE
    d = o.adjudicate_dispute(upheld=False, new_freeze_tag="freeze-Mtest-1")
    assert o.phase == Phase.IMPLEMENTING
    assert o.record.freeze_tag == "freeze-Mtest-1"
    assert d.action == Action.CONTINUE


def test_repeated_disputes_pause() -> None:
    o = at_implementing(targets=())
    o.record.dispute_count = 2  # already at the cap
    o.record_iteration(ev(0, pass_count=3, dispute="T9"))
    d = o.adjudicate_dispute(upheld=True)
    assert d.action == Action.PAUSE
    assert o.phase == Phase.PAUSED
