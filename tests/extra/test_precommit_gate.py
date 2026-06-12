"""The pre-commit gate: each check catches the exact failure mode it exists for."""

from __future__ import annotations

import subprocess
from pathlib import Path

from graphed_orchestrator.precommit import (
    check_integrity,
    check_pytest,
    check_toml,
    check_workflows,
    run_gate,
)


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
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
    assert "integrity-scan" in results and "ruff" in results


def test_exclusions_downgrade_shape_findings_to_advisory(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    (repo / "pyproject.toml").write_text(
        '[tool.graphed_precommit]\nintegrity_exclude = ["scanner_tests.py"]\n'
    )
    (repo / "scanner_tests.py").write_text("import pytest\n\n@pytest.mark.skip\ndef test_x():\n    pass\n")
    result = check_integrity(repo)
    assert result.status == "ok"  # excluded -> not a hard failure
    assert "excluded:" in result.detail  # ... but VISIBLE, never silenced


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
