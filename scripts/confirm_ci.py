#!/usr/bin/env python3
"""Block until the CI for the EXACT pushed commit of one or more repos is terminal, and exit 0 only
if every repo's pinned commit is green.

This is the permanent replacement for ad-hoc shell `gh run watch` loops (which were also prone to a
zsh `set -- $unquoted` word-splitting bug when driving several repos at once). It is pure Python:
arguments are parsed by argparse, never re-split by a shell, and the SHA is resolved per repo so a
milestone can never be confirmed off a CI run for a different/earlier commit.

Usage:
    python scripts/confirm_ci.py ORG/repo                 # uses that repo's current local HEAD sha
    python scripts/confirm_ci.py ORG/repo=<sha> ORG/r2    # explicit shas; mix as needed
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from graphed_orchestrator import CiState, wait_for_ci


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
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("targets", nargs="+", help="ORG/repo or ORG/repo=<sha>")
    ap.add_argument("--timeout-s", type=float, default=2400.0)
    ap.add_argument("--poll-s", type=float, default=20.0)
    args = ap.parse_args(argv)

    all_green = True
    for token in args.targets:
        repo, sha = _parse_target(token)
        print(f"[confirm-ci] waiting for {repo}@{sha[:8]} ...", flush=True)
        state = wait_for_ci(repo, sha, timeout_s=args.timeout_s, poll_s=args.poll_s)
        ok = state is CiState.GREEN
        all_green &= ok
        print(f"[confirm-ci] {repo}@{sha[:8]}: {state.value.upper()}{'' if ok else '  <-- NOT GREEN'}")
    if not all_green:
        print("[confirm-ci] refusing to mark DONE: at least one pinned commit is not green", file=sys.stderr)
        return 1
    print("[confirm-ci] all pinned commits green — safe to mark DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
