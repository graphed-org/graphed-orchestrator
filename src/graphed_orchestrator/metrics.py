"""Deterministic metric derivation (plan B.4).

Hashes are content-addressed and stable across runs so that two identical iterations produce
identical `fail_set_hash`/`tree_hash` — the basis for the no-progress, repeat-failure, and
oscillation signals.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from .model import GateReport, IterationEvidence, IterationMetrics


def fail_set_hash(failing_test_ids: Iterable[str]) -> str:
    """Stable hash of the *set* of failing test IDs (order-independent)."""
    joined = "\n".join(sorted(set(failing_test_ids)))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def build_metrics(ev: IterationEvidence, gates: GateReport) -> IterationMetrics:
    """Project raw evidence + gate verdicts into the persisted metric row."""
    return IterationMetrics(
        iteration_index=ev.iteration_index,
        pass_count=ev.pass_count,
        fail_set_hash=fail_set_hash(ev.failing_test_ids),
        tree_hash=ev.source_tree_hash,
        diff_lines=ev.diff_lines,
        coverage_ok=gates.coverage is True,
        benchmark_ok=gates.benchmark,
        lint_ok=gates.lint,
        types_ok=gates.types,
        determinism_ok=gates.determinism,
        integrity_ok=gates.integrity_scan is True,
        tokens_spent=ev.tokens_spent,
        wall_clock_s=ev.wall_clock_s,
    )
