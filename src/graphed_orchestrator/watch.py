"""Streaming CI watcher: one event per workflow run reaching a terminal state (the monitor form).

``ci.py`` answers the orchestrator's gate question — *is the pinned commit green yet?* — as a
single blocking verdict. This module is the EVENT-STREAM companion used to drive notification
monitors while a multi-repo push settles: every (repo, sha) target is polled together, each
workflow run is reported ONCE when it completes (success **and** failure — silence must never be
mistakable for "still running"), transient query failures are themselves reported, and the watch
ends when every target has settled.

Posterity notes (2026-06-10, the dask-parity push):
- The shell ancestor of this watcher drove several repos from one string and silently watched
  nothing: **zsh does not word-split unquoted parameters**, so ``for spec in $specs`` looped once
  over the whole string, every ``gh`` call 404'd into ``2>/dev/null``, and the monitor sat quiet
  forever. Targets here are a parsed list — no shell re-splitting can exist.
- A second zsh trap: ``$repo[...]`` parses as a subscript expression inside double quotes.
- Coverage rule for monitors: emit on every terminal state and on query errors; a filter that only
  matches the happy path turns a crash into silence.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

QueryFn = Callable[[str], Sequence[Mapping[str, object]]]
EmitFn = Callable[[str], None]


class WatchResult(StrEnum):
    ALL_GREEN = "all-green"  # every target settled, every run succeeded
    FAILURES = "failures"  # every target settled, at least one run did not succeed
    TIMEOUT = "timeout"  # targets still pending when the deadline passed
    QUERY_ERROR = "query-error"  # a target's queries failed persistently (bad repo name, auth, ...)


@dataclass(frozen=True)
class RunEvent:
    """One workflow run of one target reaching a terminal state."""

    repo: str
    branch: str
    workflow: str
    conclusion: str

    @property
    def ok(self) -> bool:
        return self.conclusion == "success"

    def line(self) -> str:
        return f"{self.repo}/{self.branch} {self.workflow}: {self.conclusion}"


def _gh_runs(repo: str) -> Sequence[Mapping[str, object]]:  # pragma: no cover - thin gh wrapper
    out = subprocess.run(
        [
            "gh",
            "run",
            "list",
            "--repo",
            repo,
            "--limit",
            "40",
            "--json",
            "name,headBranch,headSha,status,conclusion",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    runs = json.loads(out or "[]")
    return runs if isinstance(runs, list) else []


def _matches(run: Mapping[str, object], sha: str) -> bool:
    head = str(run.get("headSha", ""))
    return bool(head) and (head.startswith(sha) or sha.startswith(head))


def terminal_events(repo: str, runs: Sequence[Mapping[str, object]], sha: str) -> list[RunEvent]:
    """The COMPLETED runs for ``sha``, as events (any conclusion — failure is an event too)."""
    return [
        RunEvent(
            repo=repo,
            branch=str(r.get("headBranch", "?")),
            workflow=str(r.get("name", "?")),
            conclusion=str(r.get("conclusion") or "unknown"),
        )
        for r in runs
        if _matches(r, sha) and str(r.get("status")) == "completed"
    ]


def pending_count(runs: Sequence[Mapping[str, object]], sha: str) -> int:
    """Runs for ``sha`` not yet completed. Zero matched runs ALSO counts as pending (a run that has
    not appeared yet must keep the watch alive — see ci.py's MISSING-is-not-green rule)."""
    matched = [r for r in runs if _matches(r, sha)]
    if not matched:
        return 1
    return sum(1 for r in matched if str(r.get("status")) != "completed")


def _error_detail(exc: subprocess.CalledProcessError) -> str:
    """The gh stderr, not just the exit status — 'could not resolve to a Repository' must reach the
    operator (a watcher that hid this once retried a misspelled repo name to its timeout)."""
    stderr = (exc.stderr or "").strip() if isinstance(exc.stderr, str) else ""
    return stderr.splitlines()[-1] if stderr else str(exc)


def watch(
    targets: Iterable[tuple[str, str]],
    *,
    emit: EmitFn,
    query: QueryFn | None = None,
    poll_s: float = 60.0,
    timeout_s: float = 2700.0,
    max_query_failures: int = 5,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> WatchResult:
    """Poll every (repo, sha) target, emitting each run's terminal line exactly once, until all
    targets settle or the deadline passes. Returns the aggregate verdict.

    ``max_query_failures`` CONSECUTIVE query failures for one target end the watch with
    ``QUERY_ERROR``: a nonexistent repo or revoked auth never heals, and retrying it quietly to
    the global timeout is one more way for a watcher to look alive while watching nothing."""
    target_list = list(targets)
    seen: set[RunEvent] = set()
    failures: dict[str, int] = {}
    deadline = clock() + timeout_s
    while True:
        any_pending = False
        for repo, sha in target_list:
            try:
                runs = query(repo) if query is not None else _gh_runs(repo)
            except subprocess.CalledProcessError as exc:
                failures[repo] = failures.get(repo, 0) + 1
                detail = _error_detail(exc)
                if failures[repo] >= max_query_failures:
                    emit(f"WATCH_QUERY_ERROR: {repo} failed {failures[repo]} consecutive queries: {detail}")
                    return WatchResult.QUERY_ERROR
                emit(f"{repo}: query failed ({failures[repo]}/{max_query_failures}, will retry): {detail}")
                any_pending = True
                continue
            failures[repo] = 0
            for event in terminal_events(repo, runs, sha):
                if event not in seen:
                    seen.add(event)
                    emit(event.line())
            if pending_count(runs, sha):
                any_pending = True
        if not any_pending:
            verdict = WatchResult.ALL_GREEN if all(e.ok for e in seen) else WatchResult.FAILURES
            emit(f"ALL_RUNS_SETTLED: {verdict}")
            return verdict
        if clock() >= deadline:
            emit("WATCH_TIMEOUT: targets still pending")
            return WatchResult.TIMEOUT
        sleep(poll_s)
