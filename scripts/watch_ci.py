#!/usr/bin/env python3
"""Stream CI events for one or more pushed commits until every run settles.

The event-stream companion to ``confirm_ci.py``: instead of one blocking green/red verdict, this
prints ONE line per workflow run as it reaches a terminal state — success and failure alike, plus
transient query errors — and exits when every target has settled. Feed it to a notification
monitor, a terminal, or a log.

Usage:
    python scripts/watch_ci.py ORG/repo                  # uses that repo's current local HEAD sha
    python scripts/watch_ci.py ORG/repo=<sha> ORG/r2     # explicit shas; mix as needed
    python scripts/watch_ci.py --poll 30 --timeout 1800 ORG/repo=<sha>

Exit status: 0 every run succeeded · 1 at least one run failed · 2 timed out while pending.

Like ``confirm_ci.py``, this exists because shell watch loops failed silently in practice (zsh
does not word-split unquoted parameters, so a `for spec in $specs` loop drove ONE malformed
target and `2>/dev/null` ate every error). Targets here are argparse-parsed and never re-split.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from graphed_orchestrator.watch import WatchResult, watch


def _local_head(repo_dir: str = ".") -> str:
    return subprocess.run(
        ["git", "-C", repo_dir, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _parse_target(token: str) -> tuple[str, str]:
    """`ORG/repo` (sha = local HEAD) or `ORG/repo=<sha>`."""
    if "=" in token:
        repo, sha = token.split("=", 1)
        return repo, sha
    return token, _local_head()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("targets", nargs="+", help="ORG/repo or ORG/repo=<sha>")
    ap.add_argument("--poll", type=float, default=60.0, help="poll interval seconds (default 60)")
    ap.add_argument("--timeout", type=float, default=2700.0, help="overall deadline seconds (default 2700)")
    args = ap.parse_args(argv)

    result = watch(
        [_parse_target(t) for t in args.targets],
        emit=lambda line: print(line, flush=True),
        poll_s=args.poll,
        timeout_s=args.timeout,
    )
    return {WatchResult.ALL_GREEN: 0, WatchResult.FAILURES: 1, WatchResult.TIMEOUT: 2}[result]


if __name__ == "__main__":
    sys.exit(main())
