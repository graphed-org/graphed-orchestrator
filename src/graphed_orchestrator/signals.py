"""Stall-signal detection over metric history (plan B.5).

Pure functions: each takes the metric history (oldest-first) plus thresholds and reports whether
the signal currently fires. The orchestrator owns the response mapping; these only detect.
"""

from __future__ import annotations

from collections.abc import Sequence

from .model import IterationMetrics, Thresholds


def no_progress(history: Sequence[IterationMetrics], t: Thresholds) -> bool:
    """#1 pass_count not strictly increasing for `no_progress` consecutive iterations."""
    if len(history) < t.no_progress:
        return False
    window = history[-t.no_progress :]
    return all(b.pass_count <= a.pass_count for a, b in zip(window, window[1:], strict=False))


def repeat_failure(history: Sequence[IterationMetrics], t: Thresholds) -> bool:
    """#2 identical fail_set_hash for `repeat_failure` consecutive iterations."""
    if len(history) < t.repeat_failure:
        return False
    window = history[-t.repeat_failure :]
    first = window[0].fail_set_hash
    return first != "" and all(m.fail_set_hash == first for m in window)


def oscillation(history: Sequence[IterationMetrics], t: Thresholds) -> bool:
    """#3 (tree_hash, fail_set_hash) cycles A,B,A,B... over a window (cycle len <= bound)."""
    if len(history) < 4:
        return False
    window = history[-t.oscillation_window :]
    keys = [(m.tree_hash, m.fail_set_hash) for m in window]
    for cycle in range(2, t.oscillation_cycle_len + 1):
        if len(keys) < cycle * 2:
            continue
        tail = keys[-(cycle * 2) :]
        if tail[:cycle] == tail[cycle:] and len(set(tail)) > 1:
            return True
    return False


def thrash(history: Sequence[IterationMetrics], t: Thresholds) -> bool:
    """#4 diff_lines over budget while pass_count flat or falling, for `thrash_iters` iters."""
    if len(history) < max(t.thrash_iters + 1, 2):
        return False
    window = history[-t.thrash_iters :]
    prev = history[-t.thrash_iters - 1]
    big = all(m.diff_lines > t.thrash_diff_lines for m in window)
    flat = all(b.pass_count <= a.pass_count for a, b in zip([prev, *window], window, strict=False))
    return big and flat


def gate_stuck(history: Sequence[IterationMetrics], t: Thresholds) -> bool:
    """#5 functional tests green but coverage/benchmark/determinism red, for `gate_stuck` iters.

    `pass_count == total` cannot be read here (history has no total), so we use the convention
    that the orchestrator records gate_stuck candidacy via coverage/determinism flags being red
    while the iteration otherwise made the suite pass (encoded by pass_count being maximal across
    the window and unchanging)."""
    if len(history) < t.gate_stuck:
        return False
    window = history[-t.gate_stuck :]
    top = max(m.pass_count for m in history)
    for m in window:
        if m.pass_count != top:
            return False
        secondary_red = (not m.coverage_ok) or (m.benchmark_ok is False) or (m.determinism_ok is False)
        if not secondary_red:
            return False
    return True


def flaky_gate(history: Sequence[IterationMetrics]) -> bool:
    """#10 a gate flips on identical tree_hash (pass->fail or fail->pass with no source change)."""
    if len(history) < 2:
        return False
    a, b = history[-2], history[-1]
    if a.tree_hash == "" or a.tree_hash != b.tree_hash:
        return False
    return (
        a.coverage_ok != b.coverage_ok
        or a.determinism_ok != b.determinism_ok
        or a.lint_ok != b.lint_ok
        or a.types_ok != b.types_ok
        or a.benchmark_ok != b.benchmark_ok
    )
