"""Stall-signal detection (plan B.5) in isolation."""

from __future__ import annotations

from graphed_orchestrator import IterationMetrics, Thresholds, signals


def m(
    i: int,
    *,
    pc: int = 3,
    fh: str = "f",
    th: str = "t",
    diff: int = 10,
    cov: bool = True,
    det: bool | None = True,
    bench: bool | None = None,
) -> IterationMetrics:
    return IterationMetrics(
        iteration_index=i,
        pass_count=pc,
        fail_set_hash=fh,
        tree_hash=th,
        diff_lines=diff,
        coverage_ok=cov,
        benchmark_ok=bench,
        lint_ok=True,
        types_ok=True,
        determinism_ok=det,
        integrity_ok=True,
        tokens_spent=0,
        wall_clock_s=0.0,
    )


T = Thresholds()


def test_no_progress() -> None:
    flat = [m(0, pc=2), m(1, pc=2), m(2, pc=2)]
    assert signals.no_progress(flat, T) is True
    rising = [m(0, pc=1), m(1, pc=2), m(2, pc=3)]
    assert signals.no_progress(rising, T) is False
    assert signals.no_progress(flat[:2], T) is False


def test_repeat_failure() -> None:
    same = [m(0, fh="a"), m(1, fh="a"), m(2, fh="a")]
    assert signals.repeat_failure(same, T) is True
    diff = [m(0, fh="a"), m(1, fh="b"), m(2, fh="a")]
    assert signals.repeat_failure(diff, T) is False


def test_oscillation() -> None:
    osc = [m(0, th="A", fh="1"), m(1, th="B", fh="2"), m(2, th="A", fh="1"), m(3, th="B", fh="2")]
    assert signals.oscillation(osc, T) is True
    monotone = [m(i, th=f"t{i}", fh=f"f{i}") for i in range(4)]
    assert signals.oscillation(monotone, T) is False


def test_thrash() -> None:
    hist = [m(0, pc=3, diff=10), m(1, pc=3, diff=500), m(2, pc=3, diff=600)]
    assert signals.thrash(hist, T) is True
    small = [m(0, pc=3, diff=10), m(1, pc=3, diff=50), m(2, pc=3, diff=60)]
    assert signals.thrash(small, T) is False


def test_gate_stuck() -> None:
    stuck = [m(i, pc=5, cov=False) for i in range(3)]
    assert signals.gate_stuck(stuck, T) is True
    moving = [m(0, pc=3, cov=False), m(1, pc=4, cov=False), m(2, pc=5, cov=False)]
    assert signals.gate_stuck(moving, T) is False
    green = [m(i, pc=5, cov=True) for i in range(3)]
    assert signals.gate_stuck(green, T) is False


def test_flaky_gate() -> None:
    flip = [m(0, th="X", det=True), m(1, th="X", det=False)]
    assert signals.flaky_gate(flip) is True
    changed_tree = [m(0, th="X", det=True), m(1, th="Y", det=False)]
    assert signals.flaky_gate(changed_tree) is False
    assert signals.flaky_gate(flip[:1]) is False
