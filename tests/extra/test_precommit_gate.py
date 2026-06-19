"""The pre-commit gate: each check catches the exact failure mode it exists for."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from graphed_orchestrator import precommit
from graphed_orchestrator.precommit import (
    _ci_coverage_cmd,
    _prek_cmd,
    check_coverage,
    check_integrity,
    check_prek,
    check_pytest,
    check_toml,
    check_workflows,
    run_gate,
)

# A minimal local ruff hook — enough for prek to actually lint and reject bad code.
PREK_RUFF_CONFIG = """\
repos:
  - repo: local
    hooks:
      - id: ruff-check
        name: ruff check
        entry: ruff check --force-exclude
        language: system
        types_or: [python, pyi]
"""


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    # bare CI runners have no global git identity; the fixture repo carries its own
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "gate@test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "gate"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "--allow-empty", "-m", "root"], check=True)
    return tmp_path


def test_invalid_toml_fails_with_the_file_named(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('dev = [\n  "a",\n, "b"]\n')  # the shipped bug, verbatim
    result = check_toml(tmp_path)
    assert result.status == "FAIL"
    assert "pyproject.toml" in result.detail


def test_valid_toml_passes(tmp_path: Path) -> None:
    (tmp_path / "ok.toml").write_text("x = [1, 2]\n")
    assert check_toml(tmp_path).status == "ok"


def test_mangled_workflow_yaml_fails(tmp_path: Path) -> None:
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("jobs:\n  test:\n   - bad\n  indent: [unclosed\n")
    assert check_workflows(tmp_path).status == "FAIL"


def test_modifying_an_existing_frozen_file_fails(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    frozen = repo / "tests" / "frozen" / "m1"
    frozen.mkdir(parents=True)
    (frozen / "test_x.py").write_text("def test_x():\n    assert 2 == 1 + 1\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "freeze"], check=True)
    (frozen / "test_x.py").write_text("def test_x():\n    assert True\n")  # the tamper
    result = check_integrity(repo)
    assert result.status == "FAIL"
    assert "frozen-modified" in result.detail


def test_a_brand_new_frozen_suite_is_advisory_not_a_failure(tmp_path: Path) -> None:
    # new frozen files are the TEST-AUTHORING deliverable; the gate notes them, never blocks
    repo = _git_repo(tmp_path)
    frozen = repo / "tests" / "frozen" / "m2"
    frozen.mkdir(parents=True)
    (frozen / "test_new.py").write_text("def test_new():\n    assert 2 == 1 + 1\n")
    result = check_integrity(repo)
    assert result.status == "ok"
    assert "new-frozen" in result.detail


def test_skip_injection_in_new_content_fails(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    (repo / "test_sneaky.py").write_text(
        "import pytest\n\n@pytest.mark.skip\ndef test_hard_thing():\n    assert 2 == 1 + 1\n"
    )
    result = check_integrity(repo)
    assert result.status == "FAIL"


def test_a_clean_diff_passes_integrity(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    (repo / "module.py").write_text("def f() -> int:\n    return 3\n")
    assert check_integrity(repo).status == "ok"


def test_zero_collected_tests_is_a_failure_not_a_pass(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    (repo / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n")
    (repo / "tests").mkdir()
    result = check_pytest(repo)
    assert result.status == "FAIL"
    assert "no tests collected" in result.detail


def test_run_gate_reports_every_check_and_skips_are_explicit(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    (repo / "ok.toml").write_text("x = 1\n")
    results = {r.name: r for r in run_gate(repo, fast=True)}
    assert results["toml-valid"].status == "ok"
    assert results["workflows-valid"].status == "skipped"  # explicit, never silently dropped
    assert "integrity-scan" in results and "prek" in results


def test_exclusions_downgrade_shape_findings_to_advisory(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    (repo / "pyproject.toml").write_text(
        '[tool.graphed_precommit]\nintegrity_exclude = ["scanner_tests.py"]\n'
    )
    (repo / "scanner_tests.py").write_text("import pytest\n\n@pytest.mark.skip\ndef test_x():\n    pass\n")
    result = check_integrity(repo)
    assert result.status == "ok"  # excluded -> not a hard failure
    assert "excluded:" in result.detail  # ... but VISIBLE, never silenced


def test_check_integrity_keeps_paths_on_a_large_diff(tmp_path: Path) -> None:
    # regression: the diff fed to the scanner must NOT be truncated. A >4000-char change ahead of
    # an excluded file's `diff --git` header used to orphan the finding's path, so the exclusion
    # match failed and an excluded skip became a false hard failure. Names are chosen so the
    # excluded file sorts first (its header lands at the truncated-away start).
    repo = _git_repo(tmp_path)
    (repo / "pyproject.toml").write_text(
        '[tool.graphed_precommit]\nintegrity_exclude = ["aaa_excluded.py"]\n'
    )
    (repo / "aaa_excluded.py").write_text("import pytest\n")
    (repo / "zzz_big.py").write_text("".join(f"x{i} = {i}\n" for i in range(800)))
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "base"], check=True)
    # a large change ahead of the excluded file, plus a skip injected into the excluded file
    (repo / "zzz_big.py").write_text("".join(f"x{i} = {i + 1}\n" for i in range(800)))
    (repo / "aaa_excluded.py").write_text("import pytest\n\n@pytest.mark.skip\ndef test_x():\n    pass\n")
    result = check_integrity(repo)
    assert result.status == "ok"  # path survived truncation -> exclusion matched -> advisory
    assert "excluded:" in result.detail


def test_check_prek_skipped_without_a_config(tmp_path: Path) -> None:
    # nothing to delegate to -> explicit skip, never a silent pass
    assert check_prek(_git_repo(tmp_path)).status == "skipped"


def test_check_prek_fails_when_no_runner_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # config present but neither prek nor uv on PATH -> honest FAIL, not a skip that hides the gate
    repo = _git_repo(tmp_path)
    (repo / ".pre-commit-config.yaml").write_text(PREK_RUFF_CONFIG)
    monkeypatch.setattr(precommit.shutil, "which", lambda _name: None)
    result = check_prek(repo)
    assert result.status == "FAIL"
    assert "prek not found" in result.detail


def test_check_prek_skips_only_mypy_when_types_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # --no-types must skip JUST mypy via SKIP, leaving ruff in force
    repo = _git_repo(tmp_path)
    (repo / ".pre-commit-config.yaml").write_text(PREK_RUFF_CONFIG)
    calls: list[tuple[list[str], dict[str, str] | None]] = []

    def fake_run(cmd: list[str], cwd: Path, *, env: dict[str, str] | None = None) -> tuple[int, str]:
        calls.append((cmd, env))
        return 0, ""

    monkeypatch.setattr(precommit.shutil, "which", lambda name: "/bin/prek" if name == "prek" else None)
    monkeypatch.setattr(precommit, "_run", fake_run)
    result = check_prek(repo, types=False)
    assert result.status == "ok"
    cmd, env = calls[0]
    assert cmd[:1] == ["prek"]
    assert env is not None and "mypy" in env.get("SKIP", "")


def test_prek_cmd_prefers_local_prek_then_falls_back_to_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(precommit.shutil, "which", lambda name: "/bin/prek" if name == "prek" else None)
    assert _prek_cmd() == ["prek"]
    monkeypatch.setattr(precommit.shutil, "which", lambda name: "/bin/uv" if name == "uv" else None)
    assert _prek_cmd() == ["uv", "tool", "run", "prek"]
    monkeypatch.setattr(precommit.shutil, "which", lambda _name: None)
    assert _prek_cmd() is None


def test_check_prek_reports_failure_from_a_nonzero_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path)
    (repo / ".pre-commit-config.yaml").write_text(PREK_RUFF_CONFIG)
    monkeypatch.setattr(precommit.shutil, "which", lambda name: "/bin/prek" if name == "prek" else None)
    monkeypatch.setattr(precommit, "_run", lambda *a, **k: (1, "ruff check...Failed"))
    result = check_prek(repo)
    assert result.status == "FAIL"
    assert "Failed" in result.detail


@pytest.mark.skipif(_prek_cmd() is None, reason="prek/uv not installed in this environment")
def test_check_prek_catches_a_real_lint_violation(tmp_path: Path) -> None:
    # the end-to-end witness: prek actually runs ruff and rejects bad code
    repo = _git_repo(tmp_path)
    (repo / ".pre-commit-config.yaml").write_text(PREK_RUFF_CONFIG)
    (repo / "bad.py").write_text("import os\n")  # F401: imported but unused
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    assert check_prek(repo).status == "FAIL"


def _cov_workflow(repo: Path, cmd: str) -> None:
    wf = repo / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "ci.yml").write_text(f"jobs:\n  test:\n    steps:\n      - name: cov\n        run: {cmd}\n")


def _pkg_repo(tmp_path: Path, *, fully_covered: bool) -> Path:
    """A minimal importable package + a coverage CI gate, covered fully or only half."""
    repo = _git_repo(tmp_path)
    (repo / "pyproject.toml").write_text(
        "[tool.coverage.run]\nbranch = true\nsource = ['pkg']\n"
        "[tool.coverage.report]\nfail_under = 90\nshow_missing = true\n"
    )
    (repo / "pkg").mkdir()
    (repo / "pkg" / "__init__.py").write_text(
        "def f(x):\n    if x > 0:\n        return 1\n    return 0\n\ndef g(x):\n    return x + 1\n"
    )
    body = "import pkg\n\ndef test_it():\n    assert pkg.f(1) == 1\n"
    if fully_covered:
        body += "    assert pkg.f(-1) == 0\n    assert pkg.g(2) == 3\n"
    (repo / "test_pkg.py").write_text(body)
    _cov_workflow(repo, "pytest --cov=pkg --cov-branch --cov-report=term-missing")
    return repo


def test_ci_coverage_cmd_extracted_from_workflow(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    _cov_workflow(repo, "pytest tests/frozen --cov=graphed_x --cov-branch --cov-report=term-missing")
    cmd = _ci_coverage_cmd(repo)
    assert cmd is not None
    assert cmd[1:] == [
        "-m",
        "pytest",
        "tests/frozen",
        "--cov=graphed_x",
        "--cov-branch",
        "--cov-report=term-missing",
    ]


def test_ci_coverage_cmd_is_none_when_ci_has_no_cov_gate(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    _cov_workflow(repo, "pytest tests/frozen -p no:cacheprovider")  # a Rust pkg: no python --cov gate
    assert _ci_coverage_cmd(repo) is None
    assert _ci_coverage_cmd(_git_repo(tmp_path / "bare")) is None  # no workflows at all


def test_ci_coverage_cmd_skips_compound_shell_lines(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    _cov_workflow(repo, "cd sub && pytest --cov=pkg")  # a chained line isn't a clean argv -> skip it
    assert _ci_coverage_cmd(repo) is None


def test_check_coverage_skipped_without_a_ci_gate(tmp_path: Path) -> None:
    assert check_coverage(_git_repo(tmp_path)).status == "skipped"


def test_check_coverage_fails_below_threshold(tmp_path: Path) -> None:
    # the exact failure mode this exists for: tests pass but coverage misses the >=90% gate
    result = check_coverage(_pkg_repo(tmp_path, fully_covered=False))
    assert result.status == "FAIL"
    assert "less than fail-under" in result.detail or "TOTAL" in result.detail


def test_check_coverage_passes_when_fully_covered(tmp_path: Path) -> None:
    assert check_coverage(_pkg_repo(tmp_path, fully_covered=True)).status == "ok"


def test_run_gate_runs_the_coverage_gate_when_ci_has_one(tmp_path: Path) -> None:
    results = {r.name: r for r in run_gate(_pkg_repo(tmp_path, fully_covered=True), docs=False, types=False)}
    assert "coverage" in results and results["coverage"].status == "ok"
    assert "pytest" not in results  # the coverage run executes the suite — no second, redundant run


def test_run_gate_no_coverage_flag_falls_back_to_plain_pytest(tmp_path: Path) -> None:
    results = {
        r.name: r
        for r in run_gate(_pkg_repo(tmp_path, fully_covered=False), docs=False, types=False, coverage=False)
    }
    assert "coverage" not in results and "pytest" in results  # --no-coverage -> plain suite, no cov gate


def test_allow_refreeze_downgrades_named_frozen_edits_loudly(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    frozen = repo / "tests" / "frozen" / "m1"
    frozen.mkdir(parents=True)
    (frozen / "test_x.py").write_text("def test_x():\n    assert 2 == 1 + 1\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "freeze"], check=True)
    (frozen / "test_x.py").write_text("def test_x():\n    assert 3 == 1 + 2\n")
    assert check_integrity(repo).status == "FAIL"  # without sanction: a violation
    sanctioned = check_integrity(repo, allow_refreeze=("tests/frozen/m1",))
    assert sanctioned.status == "ok"
    assert "REFREEZE:" in sanctioned.detail  # loud, named, never silent
