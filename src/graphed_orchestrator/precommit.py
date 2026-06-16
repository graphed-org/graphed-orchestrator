"""The pre-commit gate: every mechanical validation a repo must pass BEFORE a commit, in one
command — so the discipline lives in a script, not in anyone's memory.

Born from observed failure modes, each of which shipped at least once when validation was a
manually-assembled shell chain:

* edits that produced **invalid TOML/YAML** (a regex grabbed the wrong bracket; a heredoc
  mangled a workflow) where the parse check ran but its failure was swallowed by statement
  chaining — here every check's exit status is collected honestly, no pipes, no chains;
* **masked exit codes** (``mypy | tail`` makes the gate's status the pipe's);
* commits touching ``tests/frozen/**`` or gate config (the integrity scan, reused from the
  iteration machinery, runs over the staged-plus-unstaged diff);
* a green suite hiding a **collection error** or a vacuous run (zero collected = fail);
* a suite that passes locally but **misses CI's >=90% coverage gate** (local pytest measured no
  coverage, so an under-covered diff sailed through review and only went red in CI) — the gate now
  runs the repo's OWN CI ``--cov`` command (read from its workflow, so it can never drift from CI).

Usage::

    python -m graphed_orchestrator.precommit [REPO_DIR] [--no-docs] [--no-types] [--fast] [--no-coverage]

Exit 0 only when every applicable check passes. Checks that do not apply to a repo (no
``docs/``, no mypy config) are reported as skipped, never silently dropped.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .integrity import DEFAULT_CONFIG_HINTS, DEFAULT_PROTECTED_PREFIXES, scan_diff


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # "ok" | "FAIL" | "skipped"
    detail: str = ""


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    return proc.returncode, (proc.stdout + proc.stderr)[-4000:]


def check_toml(repo: Path) -> CheckResult:
    bad: list[str] = []
    for path in sorted(repo.rglob("*.toml")):
        if any(part in {".git", ".venv", "node_modules", "_build", "target"} for part in path.parts):
            continue
        try:
            tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as err:
            bad.append(f"{path.relative_to(repo)}: {err}")
    return CheckResult("toml-valid", "FAIL" if bad else "ok", "; ".join(bad))


def check_workflows(repo: Path) -> CheckResult:
    wf = repo / ".github" / "workflows"
    if not wf.is_dir():
        return CheckResult("workflows-valid", "skipped", "no workflows")
    try:
        import yaml  # noqa: PLC0415
    except ImportError:  # pragma: no cover - pyyaml is a dev dep of this repo
        return CheckResult("workflows-valid", "skipped", "pyyaml not installed")
    bad: list[str] = []
    for path in sorted(wf.glob("*.yml")) + sorted(wf.glob("*.yaml")):
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as err:
            bad.append(f"{path.name}: {err}")
    return CheckResult("workflows-valid", "FAIL" if bad else "ok", "; ".join(bad))


def check_integrity(repo: Path, *, allow_refreeze: tuple[str, ...] = ()) -> CheckResult:
    """The integrity scan over everything about to be committed (worktree vs HEAD, untracked
    included). MODIFYING an existing frozen file is a hard failure — unless its prefix is
    explicitly sanctioned via ``allow_refreeze`` (the plan's test-dispute correction path:
    amend, re-run sanity, re-freeze at a NEW tag), which downgrades it to a LOUD advisory.
    Brand-NEW files under ``tests/frozen/`` are the legitimate test-authoring deliverable and
    only advisory. The gate-gaming shapes (skip/xfail injections, tautologies, stubs) are hard
    failures wherever they appear in the new content."""
    code, diff = _run(["git", "diff", "HEAD", "--", "."], repo)
    if code != 0:
        return CheckResult("integrity-scan", "FAIL", "git diff failed (not a repo?)")
    code, changed = _run(["git", "diff", "HEAD", "--name-only", "--", "."], repo)
    code2, untracked = _run(["git", "ls-files", "--others", "--exclude-standard"], repo)
    if code or code2:
        return CheckResult("integrity-scan", "FAIL", "git file listing failed")
    frozen_modified = [
        p for p in changed.splitlines() if any(p.startswith(pre) for pre in DEFAULT_PROTECTED_PREFIXES)
    ]
    refrozen = [p for p in frozen_modified if _is_excluded(p, allow_refreeze)]
    frozen_modified = [p for p in frozen_modified if not _is_excluded(p, allow_refreeze)]
    new_frozen = [
        p for p in untracked.splitlines() if any(p.startswith(pre) for pre in DEFAULT_PROTECTED_PREFIXES)
    ]
    # untracked files participate in the shape scan as pseudo-diffs of pure additions
    pseudo = []
    for rel in untracked.splitlines():
        path = repo / rel
        if path.suffix in {".py", ".rs", ".toml", ".yml", ".yaml"} and path.is_file():
            body = "".join(
                f"+{line}\n" for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            )
            pseudo.append(f"diff --git a/{rel} b/{rel}\n--- /dev/null\n+++ b/{rel}\n{body}")
    findings = scan_diff(
        diff + "\n" + "\n".join(pseudo),
        protected_prefixes=(),  # frozen handled above with the modify-vs-new distinction
        config_hints=DEFAULT_CONFIG_HINTS,
    )
    # a repo may EXCLUDE specific paths from the shape scan (the scanner's own source and the
    # tests that test it legitimately contain the banned shapes) — visible in pyproject under
    # [tool.graphed_precommit].integrity_exclude, and downgraded to advisory, never silenced
    excluded = _integrity_exclusions(repo)
    hard_shapes = [f for f in findings if "config" not in f.code and not _is_excluded(f.path, excluded)]
    advisory_shapes = [f for f in findings if "config" not in f.code and _is_excluded(f.path, excluded)]
    hard = [f"frozen-modified:{p}" for p in frozen_modified] + [f"{f.code}:{f.path}" for f in hard_shapes]
    soft = (
        [f"REFREEZE:{p}" for p in refrozen]
        + [f"new-frozen:{p}" for p in new_frozen]
        + [f"excluded:{f.code}:{f.path}" for f in advisory_shapes]
        + [f"{f.code}:{f.path}" for f in findings if "config" in f.code]
    )
    detail = "; ".join(hard + soft)
    return CheckResult("integrity-scan", "FAIL" if hard else "ok", detail)


def _integrity_exclusions(repo: Path) -> tuple[str, ...]:
    cfg = repo / "pyproject.toml"
    if not cfg.is_file():
        return ()
    try:
        data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return ()  # toml-valid reports the parse failure; no exclusions apply
    raw = data.get("tool", {}).get("graphed_precommit", {}).get("integrity_exclude", [])
    return tuple(str(p) for p in raw)


def _is_excluded(path: str, excluded: tuple[str, ...]) -> bool:
    return any(path == e or path.startswith(e.rstrip("/") + "/") for e in excluded)


def check_ruff(repo: Path) -> CheckResult:
    code1, out1 = _run([sys.executable, "-m", "ruff", "check", "."], repo)
    code2, out2 = _run([sys.executable, "-m", "ruff", "format", "--check", "."], repo)
    return CheckResult("ruff", "FAIL" if code1 or code2 else "ok", (out1 + out2).strip()[-300:])


def check_mypy(repo: Path) -> CheckResult:
    cfg = repo / "pyproject.toml"
    if not (cfg.is_file() and "[tool.mypy]" in cfg.read_text(encoding="utf-8")):
        return CheckResult("mypy", "skipped", "no mypy config")
    code, out = _run([sys.executable, "-m", "mypy"], repo)
    return CheckResult("mypy", "FAIL" if code else "ok", out.strip()[-300:])


def check_pytest(repo: Path) -> CheckResult:
    code, out = _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], repo)
    if code == 5:  # nothing collected: a vacuous "green" is a failure here
        return CheckResult("pytest", "FAIL", "no tests collected")
    return CheckResult(
        "pytest", "FAIL" if code else "ok", out.strip().splitlines()[-1] if out.strip() else ""
    )


def _ci_coverage_cmd(repo: Path) -> list[str] | None:
    """The repo's OWN CI coverage command, read straight from its workflow, so the local gate runs
    coverage EXACTLY as CI does and can never silently drift from it (the gap that let an 86% frozen
    suite pass local checks yet fail CI's ``--cov`` gate). Returns the ``pytest ... --cov`` invocation
    as argv — ``fail_under`` then comes from the repo's ``[tool.coverage.report]``, honored identically
    — or ``None`` when CI has no Python coverage gate (e.g. a Rust package whose coverage is
    ``cargo llvm-cov``, or the meta repo). Reading the workflow rather than hard-coding ``tests/frozen``
    is deliberate: repos differ (most gate the frozen suite only; the orchestrator gates the whole
    suite), and the workflow is the single source of truth for what CI will actually enforce."""
    wf = repo / ".github" / "workflows"
    if not wf.is_dir():
        return None
    for path in sorted(wf.glob("*.yml")) + sorted(wf.glob("*.yaml")):
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line.startswith("- "):
                line = line[2:].strip()
            if line.startswith("run:"):
                line = line[4:].strip()
            if "pytest" not in line or "--cov" not in line:
                continue
            if any(sep in line for sep in ("&&", "|", ";")):
                continue  # a compound shell line isn't a clean argv — skip rather than mis-split it
            toks = shlex.split(line)
            if "pytest" in toks:
                return [sys.executable, "-m", *toks[toks.index("pytest") :]]
    return None


def check_coverage(repo: Path, *, cmd: list[str] | None = None) -> CheckResult:
    """Run the repo's CI coverage command locally so the >=90% line+branch gate (plan §B.3) is caught
    BEFORE the push, not discovered red in CI. A non-zero exit is either a test failure or a
    ``fail_under`` miss — both must block the commit. ``skipped`` when the repo has no CI ``--cov``
    gate, so the check is harmless to run anywhere."""
    cmd = cmd if cmd is not None else _ci_coverage_cmd(repo)
    if cmd is None:
        return CheckResult("coverage", "skipped", "no pytest --cov gate in CI")
    code, out = _run([*cmd, "-p", "no:cacheprovider"], repo)
    if code == 5:  # the gated suite collected nothing — a vacuous "100%" is still a failure
        return CheckResult("coverage", "FAIL", "no tests collected")
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    failmsg = next((ln for ln in lines if "Coverage failure" in ln), "")
    total = next((ln for ln in reversed(lines) if ln.startswith("TOTAL")), "")
    return CheckResult(
        "coverage", "FAIL" if code else "ok", (failmsg or total or (lines[-1] if lines else ""))[:160]
    )


def check_docs(repo: Path) -> CheckResult:
    docs = repo / "docs"
    if not (docs / "conf.py").is_file():
        return CheckResult("sphinx -W", "skipped", "no docs/")
    import tempfile  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        code, out = _run([sys.executable, "-m", "sphinx", "-W", "-q", "-b", "html", "docs", tmp], repo)
    return CheckResult("sphinx -W", "FAIL" if code else "ok", out.strip()[-300:])


def run_gate(
    repo: Path,
    *,
    docs: bool = True,
    types: bool = True,
    fast: bool = False,
    coverage: bool = True,
    allow_refreeze: tuple[str, ...] = (),
) -> list[CheckResult]:
    checks = [
        check_toml(repo),
        check_workflows(repo),
        check_integrity(repo, allow_refreeze=allow_refreeze),
        check_ruff(repo),
    ]
    if types:
        checks.append(check_mypy(repo))
    if not fast:
        # When CI has a coverage gate, run THAT command — it executes the gated suite AND enforces
        # >=90% in one pass, so we mirror CI exactly without running pytest twice. Otherwise (no CI
        # --cov gate, or --no-coverage) fall back to the plain suite for correctness.
        cov_cmd = _ci_coverage_cmd(repo) if coverage else None
        checks.append(check_coverage(repo, cmd=cov_cmd) if cov_cmd is not None else check_pytest(repo))
        if docs:
            checks.append(check_docs(repo))
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("repo", nargs="?", default=".", help="repository directory (default: cwd)")
    parser.add_argument("--no-docs", action="store_true", help="skip the sphinx -W build")
    parser.add_argument("--no-types", action="store_true", help="skip mypy")
    parser.add_argument("--fast", action="store_true", help="static checks only (no pytest/docs)")
    parser.add_argument(
        "--no-coverage",
        action="store_true",
        help="run the plain test suite without CI's coverage gate (faster; not push-safe)",
    )
    parser.add_argument(
        "--allow-refreeze",
        action="append",
        default=[],
        metavar="PREFIX",
        help="sanction a freeze AMENDMENT under this prefix (loud advisory; must re-tag)",
    )
    ns = parser.parse_args(argv)

    repo = Path(ns.repo).resolve()
    results = run_gate(
        repo,
        docs=not ns.no_docs,
        types=not ns.no_types,
        fast=ns.fast,
        coverage=not ns.no_coverage,
        allow_refreeze=tuple(ns.allow_refreeze),
    )
    width = max(len(r.name) for r in results)
    failed = False
    for r in results:
        marker = {"ok": "ok ", "FAIL": "FAIL", "skipped": "-- "}[r.status]
        print(f"  {r.name:<{width}}  {marker}  {r.detail[:160]}")
        failed = failed or r.status == "FAIL"
    print("PRECOMMIT-GATE:", "FAIL" if failed else "ok", f"({repo.name})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
