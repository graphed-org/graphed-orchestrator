"""Unit tests for the streaming CI watcher (scripts/watch_ci.py's engine).

All queries are injected — no network. The properties pinned here are the ones whose absence made
the shell ancestor fail silently: every terminal state is an event (failure included), a missing
or errored query keeps the watch alive AND emits, each run is reported exactly once, and the
aggregate verdict reflects every seen conclusion.
"""

from __future__ import annotations

import importlib.util
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from graphed_orchestrator.watch import WatchResult, pending_count, terminal_events, watch


def _run(name: str, sha: str, status: str, conclusion: str | None, branch: str = "main") -> dict[str, object]:
    return {"name": name, "headSha": sha, "status": status, "conclusion": conclusion, "headBranch": branch}


SHA_A = "aaaa111"
SHA_B = "bbbb222"


def test_terminal_events_report_every_conclusion_once_decoded() -> None:
    runs = [
        _run("ci", SHA_A, "completed", "success"),
        _run("wheels", SHA_A, "completed", "failure"),
        _run("ci", SHA_A, "in_progress", None),
        _run("ci", "other", "completed", "success"),  # different sha: not ours
    ]
    events = terminal_events("org/r", runs, SHA_A)
    assert {e.line() for e in events} == {"org/r/main ci: success", "org/r/main wheels: failure"}
    assert {e.ok for e in events} == {True, False}


def test_pending_counts_unfinished_and_missing_runs() -> None:
    assert pending_count([_run("ci", SHA_A, "queued", None)], SHA_A) == 1
    assert pending_count([_run("ci", SHA_A, "completed", "success")], SHA_A) == 0
    assert pending_count([], SHA_A) == 1  # a run that has not appeared yet is PENDING, not done


def test_watch_emits_each_run_once_and_settles_green() -> None:
    polls = [
        [_run("ci", SHA_A, "queued", None)],
        [_run("ci", SHA_A, "completed", "success"), _run("wheels", SHA_A, "in_progress", None)],
        [_run("ci", SHA_A, "completed", "success"), _run("wheels", SHA_A, "completed", "success")],
    ]
    calls = iter(polls)
    lines: list[str] = []
    result = watch(
        [("org/r", SHA_A)],
        emit=lines.append,
        query=lambda repo: next(calls),
        sleep=lambda s: None,
        clock=lambda: 0.0,
    )
    assert result is WatchResult.ALL_GREEN
    assert lines == [
        "org/r/main ci: success",
        "org/r/main wheels: success",
        "ALL_RUNS_SETTLED: all-green",
    ]


def test_watch_reports_failures_in_the_verdict() -> None:
    polls = iter([[_run("ci", SHA_A, "completed", "failure")]])
    lines: list[str] = []
    result = watch(
        [("org/r", SHA_A)],
        emit=lines.append,
        query=lambda repo: next(polls),
        sleep=lambda s: None,
        clock=lambda: 0.0,
    )
    assert result is WatchResult.FAILURES
    assert lines[0] == "org/r/main ci: failure"  # the failure IS an event, not silence


def test_watch_covers_multiple_targets_and_branches() -> None:
    state: dict[str, Sequence[Mapping[str, object]]] = {
        "org/r1": [_run("ci", SHA_A, "completed", "success")],
        "org/r2": [_run("ci", SHA_B, "completed", "success", branch="backup/x")],
    }
    lines: list[str] = []
    result = watch(
        [("org/r1", SHA_A), ("org/r2", SHA_B)],
        emit=lines.append,
        query=lambda repo: state[repo],
        sleep=lambda s: None,
        clock=lambda: 0.0,
    )
    assert result is WatchResult.ALL_GREEN
    assert "org/r2/backup/x ci: success" in lines


def test_transient_query_failure_is_an_event_and_keeps_watching() -> None:
    boom = subprocess.CalledProcessError(1, ["gh"])
    polls = iter([boom, [_run("ci", SHA_A, "completed", "success")]])

    def query(repo: str) -> Sequence[Mapping[str, object]]:
        item = next(polls)
        if isinstance(item, subprocess.CalledProcessError):
            raise item
        return item

    lines: list[str] = []
    result = watch(
        [("org/r", SHA_A)],
        emit=lines.append,
        query=query,
        sleep=lambda s: None,
        clock=lambda: 0.0,
    )
    assert result is WatchResult.ALL_GREEN
    assert any("query failed (transient" in line for line in lines)  # errors are NEVER silent


def test_watch_times_out_while_pending() -> None:
    ticks = iter([0.0, 10.0, 20.0, 50.0, 100.0, 200.0, 400.0, 800.0, 1600.0, 3200.0])
    lines: list[str] = []
    result = watch(
        [("org/r", SHA_A)],
        emit=lines.append,
        query=lambda repo: [_run("ci", SHA_A, "queued", None)],
        sleep=lambda s: None,
        clock=lambda: next(ticks),
        timeout_s=100.0,
    )
    assert result is WatchResult.TIMEOUT
    assert lines[-1] == "WATCH_TIMEOUT: targets still pending"


def test_cli_target_parsing() -> None:
    spec = importlib.util.spec_from_file_location(
        "watch_ci", Path(__file__).resolve().parents[2] / "scripts" / "watch_ci.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._parse_target("org/repo=abc123") == ("org/repo", "abc123")
    with pytest.raises(SystemExit):
        mod.main(["--poll", "1", "--timeout", "1"])  # no targets: argparse exits
