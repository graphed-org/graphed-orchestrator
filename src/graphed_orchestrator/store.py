"""Durable state backing (plan B.4/B.7).

Reads/writes the per-repo `.graphed/state.json` and appends to `.graphed/<Mx>/attempts.md` so the
orchestrator's decisions survive a context reset. JSON is written with sorted keys for
byte-stable, diff-friendly output.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .model import GateReport, IterationMetrics, MilestoneRecord, Phase


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gate_dict(g: GateReport) -> dict[str, bool | None]:
    return {
        "frozen_tests": g.frozen_tests,
        "coverage": g.coverage,
        "lint": g.lint,
        "types": g.types,
        "determinism": g.determinism,
        "benchmark": g.benchmark,
        "integrity_scan": g.integrity_scan,
    }


def _metric_dict(m: IterationMetrics) -> dict[str, object]:
    return {
        "iteration_index": m.iteration_index,
        "pass_count": m.pass_count,
        "fail_set_hash": m.fail_set_hash,
        "tree_hash": m.tree_hash,
        "diff_lines": m.diff_lines,
        "coverage_ok": m.coverage_ok,
        "benchmark_ok": m.benchmark_ok,
        "lint_ok": m.lint_ok,
        "types_ok": m.types_ok,
        "determinism_ok": m.determinism_ok,
        "integrity_ok": m.integrity_ok,
        "tokens_spent": m.tokens_spent,
        "wall_clock_s": m.wall_clock_s,
    }


def milestone_to_dict(rec: MilestoneRecord) -> dict[str, object]:
    """Serialize a milestone record into the state.json `milestones[<id>]` shape."""
    latest = rec.gates[-1] if rec.gates else GateReport()
    return {
        "phase": rec.phase.value,
        "freeze_tag": rec.freeze_tag,
        "reject_count": rec.reject_count,
        "dispute_count": rec.dispute_count,
        "l0_count": rec.l0_count,
        "escalated": rec.escalated,
        "incident": rec.incident,
        "gates": _gate_dict(latest),
        "metrics_history": [_metric_dict(m) for m in rec.metrics],
    }


def write_state(path: Path, repo: str, records: list[MilestoneRecord]) -> None:
    """Write a per-repo `.graphed/state.json` from milestone records."""
    payload = {
        "schema_version": 1,
        "repo": repo,
        "updated_at": _utc_now(),
        "milestones": {rec.milestone_id: milestone_to_dict(rec) for rec in records},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_attempt(attempts_path: Path, rec: MilestoneRecord, *, summary: str) -> None:
    """Append one structured iteration entry to attempts.md (plan B.4)."""
    attempts_path.parent.mkdir(parents=True, exist_ok=True)
    idx = rec.metrics[-1].iteration_index if rec.metrics else len(rec.metrics)
    gate = rec.gates[-1] if rec.gates else GateReport()
    lines = [
        f"## Iteration {idx} — phase {rec.phase.value} — {_utc_now()}",
        "",
        f"- summary: {summary}",
        f"- gates: {_gate_dict(gate)}",
        f"- l0_count={rec.l0_count} escalated={rec.escalated} reject_count={rec.reject_count}",
        "",
    ]
    with attempts_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def is_done(rec: MilestoneRecord) -> bool:
    return rec.phase == Phase.DONE
