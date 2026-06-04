"""B.8 end-to-end faker scenarios: simulate agent behaviors, assert the correct response."""

from __future__ import annotations

from fakers import TOTAL, at_implementing, ev

from graphed_orchestrator import Action, GateReport, Phase, Thresholds


def test_steady_progress_reaches_done() -> None:
    """A faker that makes steady progress and finally goes green is APPROVED to DONE."""
    o = at_implementing()
    assert o.record_iteration(ev(0, pass_count=2)).action == Action.CONTINUE
    assert o.record_iteration(ev(1, pass_count=4)).action == Action.CONTINUE
    final = o.record_iteration(ev(2, pass_count=TOTAL))
    assert final.action == Action.ADVANCE
    assert o.phase == Phase.REVIEW
    green = GateReport(
        frozen_tests=True, coverage=True, lint=True, types=True, determinism=True, integrity_scan=True
    )
    decision = o.review(approve=True, gates=green)
    assert decision.action == Action.ADVANCE
    assert o.phase == Phase.DONE


def test_oscillating_faker_pauses() -> None:
    """A,B,A,B oscillation escalates then trips the circuit breaker."""
    o = at_implementing()
    states = [
        ("A", ("T2", "T3")),
        ("B", ("T1", "T4")),
        ("A", ("T2", "T3")),
        ("B", ("T1", "T4")),
        ("A", ("T2", "T3")),
    ]
    actions = []
    for i, (tree, failing) in enumerate(states):
        d = o.record_iteration(ev(i, pass_count=3, tree=tree, failing=failing))
        actions.append(d.action)
        if d.action == Action.PAUSE:
            break
    assert Action.ESCALATE_L1 in actions
    assert actions[-1] == Action.PAUSE
    assert o.phase == Phase.PAUSED


def test_tampering_faker_pauses_with_incident() -> None:
    """Touching the frozen suite is an immediate integrity incident -> PAUSE."""
    o = at_implementing()
    d = o.record_iteration(ev(0, pass_count=TOTAL, touched=True))
    assert d.action == Action.PAUSE
    assert d.incident is True
    assert o.phase == Phase.PAUSED
    assert o.record.incident is not None


def test_tampering_detected_via_diff_scan() -> None:
    """The same tamper caught through the diff integrity scan (not a self-reported flag)."""
    o = at_implementing()
    diff = (
        "--- a/tests/frozen/orch/test_x.py\n"
        "+++ b/tests/frozen/orch/test_x.py\n"
        "-    assert result == expected\n"
        "+    assert True\n"
    )
    d = o.record_iteration(ev(0, pass_count=TOTAL), diff_text=diff)
    assert d.action == Action.PAUSE
    assert d.incident is True


def test_stalling_faker_climbs_the_ladder() -> None:
    """Flat pass_count: L0, L0, then L1, then L2 PAUSE."""
    o = at_implementing(thresholds=Thresholds(no_progress=3, r_retry=2))
    seq = [o.record_iteration(ev(i, pass_count=2, tree=f"t{i}")).action for i in range(6)]
    assert seq[:2] == [Action.CONTINUE, Action.CONTINUE]
    assert seq[2] == Action.RETRY_L0
    assert seq[3] == Action.RETRY_L0
    assert seq[4] == Action.ESCALATE_L1
    assert seq[5] == Action.PAUSE
    assert o.phase == Phase.PAUSED


def test_disputing_faker_enters_test_dispute() -> None:
    """Filing a dispute pauses coding for the milestone and routes to adjudication."""
    o = at_implementing()
    d = o.record_iteration(ev(0, pass_count=3, dispute="tests/frozen/orch/test_x::T1"))
    assert d.action == Action.DISPUTE
    assert o.phase == Phase.TEST_DISPUTE
    # adjudication: test upheld -> back to implementing.
    back = o.adjudicate_dispute(upheld=True)
    assert back.phase == Phase.IMPLEMENTING


def test_flaky_gate_quarantined_then_pauses() -> None:
    """A gate flipping on identical tree_hash is quarantined, then PAUSEs if it persists."""
    o = at_implementing(thresholds=Thresholds(flaky_persist=2))
    o.record_iteration(ev(0, pass_count=3, tree="X", det=True))
    d1 = o.record_iteration(ev(1, pass_count=3, tree="X", det=False))
    assert d1.action == Action.QUARANTINE
    d2 = o.record_iteration(ev(2, pass_count=3, tree="X", det=True))
    assert d2.action == Action.QUARANTINE
    d3 = o.record_iteration(ev(3, pass_count=3, tree="X", det=False))
    assert d3.action == Action.PAUSE
    assert o.phase == Phase.PAUSED


def test_budget_exceeded_pauses_immediately() -> None:
    """Exceeding the iteration cap is an immediate circuit breaker (B.5 #6)."""
    from graphed_orchestrator import Budget

    o = at_implementing(budget=Budget(iterations_cap=3))
    assert o.record_iteration(ev(0, pass_count=2)).action == Action.CONTINUE
    d = o.record_iteration(ev(3, pass_count=2))
    assert d.action == Action.PAUSE
    assert "budget" in (o.record.incident or "")
