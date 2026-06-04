"""Faker agent behaviors for the B.8 orchestrator self-test.

Each faker is a deterministic generator of `IterationEvidence`. The tests drive a real
`Orchestrator` with these and assert the mechanically-correct transition/response. A pipeline that
cannot detect the tampering faker here must not be used to run real agents (plan B.8).
"""

from __future__ import annotations

from graphed_orchestrator import (
    IterationEvidence,
    Orchestrator,
    SanityReport,
    Thresholds,
)
from graphed_orchestrator.gates import evaluate_test_sanity

TOTAL = 5


def at_implementing(*, targets: tuple[str, ...] = (), budget=None, thresholds=None) -> Orchestrator:
    """Drive a fresh milestone deterministically to the IMPLEMENTING phase."""
    o = Orchestrator(
        "Mtest", budget=budget, thresholds=thresholds or Thresholds(), implementation_targets=targets
    )
    o.start()
    o.begin_test_authoring()
    rep: SanityReport = evaluate_test_sanity(
        collects=True,
        stub_pass_count=0,
        stub_total=TOTAL,
        stub_run1_fail_hash="stub",
        stub_run2_fail_hash="stub",
        coverage_instrumented=True,
    )
    o.run_test_sanity(rep)
    o.freeze("freeze-Mtest-0")
    return o


def ev(
    i: int,
    *,
    pass_count: int,
    total: int = TOTAL,
    failing: tuple[str, ...] | None = None,
    tree: str = "tree",
    diff: int = 10,
    coverage: tuple[float, float] | None = (95.0, 95.0),
    from_frozen: bool = True,
    lint: bool | None = True,
    types: bool | None = True,
    det: bool | None = True,
    bench: bool | None = None,
    touched: bool = False,
    integ: tuple[str, ...] = (),
    tokens: int = 0,
    wall: float = 0.0,
    dispute: str | None = None,
) -> IterationEvidence:
    """Build one iteration's evidence with analysis-friendly defaults (all-green when full)."""
    if failing is None:
        failing = tuple(f"T{j}" for j in range(pass_count, total))
    cl, cb = coverage if coverage is not None else (None, None)
    return IterationEvidence(
        iteration_index=i,
        pass_count=pass_count,
        total_tests=total,
        failing_test_ids=failing,
        source_tree_hash=tree,
        diff_lines=diff,
        coverage_line=cl,
        coverage_branch=cb,
        coverage_from_frozen=from_frozen,
        lint_ok=lint,
        types_ok=types,
        determinism_ok=det,
        benchmark_ok=bench,
        frozen_tests_touched=touched,
        integrity_findings=integ,
        tokens_spent=tokens,
        wall_clock_s=wall,
        dispute_filed=dispute,
    )
