"""CI verification for the *exact commit being marked DONE* (the fix for a real failure: a milestone
was marked DONE off a CI run for a different/earlier commit, while the pinned commit's CI was still
``in_progress``).

The rule is strict and deterministic: a commit's CI is **green only when a run for that SHA has
COMPLETED with conclusion ``success``**. ``in_progress`` / ``queued`` / no-run-found all count as
NOT green, so DONE can never be recorded off an unfinished run. `wait_for_ci` polls until the SHA's
run actually completes.

The gh call is injected (`query`) so the logic is unit-testable without a network.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum

# (status, conclusion) -> a tri-state verdict
QueryFn = Callable[[str], Sequence[Mapping[str, object]]]


class CiState(StrEnum):
    GREEN = "green"  # completed + success -> safe to mark DONE
    PENDING = "pending"  # queued / in_progress -> NOT green, must wait
    FAILED = "failed"  # completed + non-success
    MISSING = "missing"  # no run found for this SHA


def _gh_query(repo: str) -> Sequence[Mapping[str, object]]:  # pragma: no cover - thin gh wrapper
    out = subprocess.run(
        ["gh", "run", "list", "--repo", repo, "--limit", "40", "--json", "headSha,status,conclusion"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    runs = json.loads(out or "[]")
    return runs if isinstance(runs, list) else []


def classify(runs: Sequence[Mapping[str, object]], sha: str) -> CiState:
    """Classify the CI state for ``sha`` from a list of runs. Any non-completed run for the SHA
    makes it PENDING (never green); only a completed ``success`` is GREEN."""
    matched = [
        r
        for r in runs
        if str(r.get("headSha", "")).startswith(sha) or sha.startswith(str(r.get("headSha", "")))
    ]
    if not matched:
        return CiState.MISSING
    # if ANY run for the sha is not yet completed, it is pending (not green)
    if any(str(r.get("status")) != "completed" for r in matched):
        return CiState.PENDING
    if all(str(r.get("conclusion")) == "success" for r in matched):
        return CiState.GREEN
    return CiState.FAILED


def ci_state(repo: str, sha: str, *, query: QueryFn | None = None) -> CiState:
    runs = query(repo) if query is not None else _gh_query(repo)
    return classify(runs, sha)


def is_ci_green(repo: str, sha: str, *, query: QueryFn | None = None) -> bool:
    """True ONLY when a completed run for ``sha`` concluded ``success`` (in_progress => False)."""
    return ci_state(repo, sha, query=query) is CiState.GREEN


def wait_for_ci(
    repo: str,
    sha: str,
    *,
    timeout_s: float = 1800.0,
    poll_s: float = 20.0,
    query: QueryFn | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> CiState:
    """Poll until the run for ``sha`` reaches a terminal state, or ``timeout_s`` elapses. Returns the
    terminal CiState (GREEN / FAILED / MISSING) — never PENDING unless it timed out."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            state = ci_state(repo, sha, query=query)
        except subprocess.CalledProcessError:
            # a transient `gh` failure (e.g. the run is not yet queryable right after a push, or a
            # momentary API blip) must NOT abort confirmation or count as green — treat it as pending
            # and keep polling until the run resolves or we time out.
            state = CiState.PENDING
        if state is not CiState.PENDING or time.monotonic() >= deadline:
            return state
        sleep(poll_s)
