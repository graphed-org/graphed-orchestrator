"""Mechanical gate rules (plan B.3)."""

from __future__ import annotations

from fakers import ev

from graphed_orchestrator import GateReport, can_record_approve, evaluate_iteration
from graphed_orchestrator.gates import evaluate_test_sanity


def test_frozen_tests_gate_requires_all_pass() -> None:
    assert evaluate_iteration(ev(0, pass_count=5, total=5)).frozen_tests is True
    assert evaluate_iteration(ev(0, pass_count=4, total=5)).frozen_tests is False
    # zero tests is never "green"
    assert evaluate_iteration(ev(0, pass_count=0, total=0, failing=())).frozen_tests is False


def test_coverage_gate_requires_threshold_and_frozen_origin() -> None:
    assert evaluate_iteration(ev(0, pass_count=5, coverage=(95.0, 92.0))).coverage is True
    assert evaluate_iteration(ev(0, pass_count=5, coverage=(89.9, 99.0))).coverage is False
    # hits only from tests/extra are rejected (B.3 #2)
    assert evaluate_iteration(ev(0, pass_count=5, coverage=(99.0, 99.0), from_frozen=False)).coverage is False
    # no coverage measured -> not-run (None)
    assert evaluate_iteration(ev(0, pass_count=5, coverage=None)).coverage is None


def test_integrity_gate_reflects_findings_and_tamper() -> None:
    assert evaluate_iteration(ev(0, pass_count=5)).integrity_scan is True
    assert evaluate_iteration(ev(0, pass_count=5, touched=True)).integrity_scan is False
    assert evaluate_iteration(ev(0, pass_count=5, integ=("tautological_assert",))).integrity_scan is False


def test_benchmark_na_does_not_block_all_green() -> None:
    g = GateReport(
        frozen_tests=True,
        coverage=True,
        lint=True,
        types=True,
        determinism=True,
        integrity_scan=True,
        benchmark=None,
    )
    assert g.all_green is True
    assert (
        GateReport(
            frozen_tests=True,
            coverage=True,
            lint=True,
            types=True,
            determinism=True,
            integrity_scan=True,
            benchmark=False,
        ).all_green
        is False
    )


def test_approve_only_on_green() -> None:
    green = GateReport(
        frozen_tests=True,
        coverage=True,
        lint=True,
        types=True,
        determinism=True,
        integrity_scan=True,
        ci=True,
    )
    red = GateReport(
        frozen_tests=True, coverage=False, lint=True, types=True, determinism=True, integrity_scan=True
    )
    assert can_record_approve(green) is True
    assert can_record_approve(red) is False


def test_approve_requires_confirmed_ci() -> None:
    # local gates all green but CI not yet confirmed (None == in_progress/unknown) -> NOT done-ready
    local_green = GateReport(
        frozen_tests=True,
        coverage=True,
        lint=True,
        types=True,
        determinism=True,
        integrity_scan=True,
        ci=None,
    )
    assert local_green.all_green is True  # the per-iteration advance gate is satisfied
    assert local_green.done_ready is False  # but DONE is not, without confirmed CI
    assert can_record_approve(local_green) is False
    # an explicitly-failed CI also blocks DONE
    failed_ci = GateReport(
        frozen_tests=True,
        coverage=True,
        lint=True,
        types=True,
        determinism=True,
        integrity_scan=True,
        ci=False,
    )
    assert can_record_approve(failed_ci) is False


def test_test_sanity_non_vacuity_and_determinism() -> None:
    # non-vacuous: the stub must FAIL the suite
    vacuous = evaluate_test_sanity(
        collects=True,
        stub_pass_count=5,
        stub_total=5,
        stub_run1_fail_hash="x",
        stub_run2_fail_hash="x",
        coverage_instrumented=True,
    )
    assert vacuous.non_vacuous is False
    assert vacuous.passed is False

    flaky = evaluate_test_sanity(
        collects=True,
        stub_pass_count=0,
        stub_total=5,
        stub_run1_fail_hash="a",
        stub_run2_fail_hash="b",
        coverage_instrumented=True,
    )
    assert flaky.deterministic is False
    assert flaky.passed is False

    good = evaluate_test_sanity(
        collects=True,
        stub_pass_count=0,
        stub_total=5,
        stub_run1_fail_hash="a",
        stub_run2_fail_hash="a",
        coverage_instrumented=True,
    )
    assert good.passed is True
