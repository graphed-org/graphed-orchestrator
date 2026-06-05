"""Mechanical gate evaluation (plan B.3).

Gates are computed from artifacts, never from agent claims. The coverage gate additionally
requires that the covering hits come from the *frozen* suite (plan B.3 #2): a milestone whose new
code is exercised only by implementer-added tests is rejected.
"""

from __future__ import annotations

from .model import GateReport, IterationEvidence, SanityReport

COVERAGE_MIN = 90.0


def evaluate_iteration(ev: IterationEvidence, *, coverage_min: float = COVERAGE_MIN) -> GateReport:
    """Evaluate the per-iteration gates for one piece of evidence."""
    frozen_tests = ev.total_tests > 0 and ev.pass_count == ev.total_tests and not ev.failing_test_ids

    coverage: bool | None
    if ev.coverage_line is None or ev.coverage_branch is None:
        coverage = None
    else:
        coverage = (
            ev.coverage_line >= coverage_min
            and ev.coverage_branch >= coverage_min
            and ev.coverage_from_frozen
        )

    integrity_clean = (not ev.frozen_tests_touched) and len(ev.integrity_findings) == 0

    return GateReport(
        frozen_tests=frozen_tests,
        coverage=coverage,
        lint=ev.lint_ok,
        types=ev.types_ok,
        determinism=ev.determinism_ok,
        benchmark=ev.benchmark_ok,
        integrity_scan=integrity_clean,
    )


def evaluate_test_sanity(
    *,
    collects: bool,
    stub_pass_count: int,
    stub_total: int,
    stub_run1_fail_hash: str,
    stub_run2_fail_hash: str,
    coverage_instrumented: bool,
) -> SanityReport:
    """TEST_SANITY (plan B.3 #1): the suite must collect, be non-vacuous against the stub
    (every frozen test red before it can be made green), be deterministic, and be instrumented."""
    non_vacuous = collects and stub_total > 0 and stub_pass_count < stub_total
    deterministic = stub_run1_fail_hash == stub_run2_fail_hash
    return SanityReport(
        collects=collects,
        non_vacuous=non_vacuous,
        deterministic=deterministic,
        coverage_instrumented=coverage_instrumented,
    )


def can_record_approve(report: GateReport) -> bool:
    """The orchestrator refuses to record DONE while any gate is red OR the commit's CI is not
    confirmed green (plan B.3 #4). `in_progress`/unknown CI counts as not-green, so a milestone can
    never be marked DONE off an un-finished CI run."""
    return report.done_ready
