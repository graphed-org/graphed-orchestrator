"""M10 — the integrity scan catches bare-`pass`/`...` Implementation Target bodies (finding C.10).

Root B.6 lists "a named Implementation Target left as bare NotImplementedError/todo!()/pass" as a
violation, but the scanner's line regex only caught the first two — `reduce_incremental` shipping
as a pass-through alias proved a semantic stub can sail past it. This pins the body-aware check:
a named target whose entire added body is `pass` or `...` is `target_stubbed`; un-named helper
code keeps its legitimate bare `pass`.
"""

from __future__ import annotations

from graphed_orchestrator.integrity import scan_diff


def _codes(diff: str, targets: tuple[str, ...] = ()) -> list[str]:
    return [f.code for f in scan_diff(diff, implementation_targets=targets)]


def _diff(*added: str, path: str = "src/x.py") -> str:
    plus = "\n".join(f"+{line}" for line in added)
    return f"--- a/{path}\n+++ b/{path}\n{plus}\n"


def test_named_target_with_pass_body_is_flagged() -> None:
    diff = _diff("def reduce_incremental(self):", "    pass")
    assert "target_stubbed" in _codes(diff, ("reduce_incremental",))


def test_named_target_with_ellipsis_body_is_flagged() -> None:
    diff = _diff("def project_buffers(array):", "    ...")
    assert "target_stubbed" in _codes(diff, ("project_buffers",))


def test_docstring_before_the_bare_pass_does_not_hide_it() -> None:
    diff = _diff(
        "def evaluate_ir(blob):",
        '    """Evaluate the reduced IR."""',
        "    pass",
    )
    assert "target_stubbed" in _codes(diff, ("evaluate_ir",))


def test_rust_fn_with_todo_still_flagged_and_pass_check_is_additive() -> None:
    diff = _diff("fn reduce_incremental() {", "    todo!()", "}", path="src/store.rs")
    assert "target_stubbed" in _codes(diff, ("reduce_incremental",))


def test_unnamed_function_with_pass_body_is_not_flagged() -> None:
    # bare `pass` is legitimate outside named targets (protocols, exception classes, helpers)
    diff = _diff("def _helper():", "    pass")
    assert "target_stubbed" not in _codes(diff, ("reduce_incremental",))


def test_no_targets_named_means_no_pass_findings() -> None:
    diff = _diff("def anything():", "    pass")
    assert "target_stubbed" not in _codes(diff)


def test_real_body_for_a_named_target_is_clean() -> None:
    diff = _diff("def reduce_incremental(self):", "    return self._do_the_work()")
    assert "target_stubbed" not in _codes(diff, ("reduce_incremental",))


def test_exception_class_pass_is_not_flagged() -> None:
    diff = _diff("class ProjectionError(GraphedError):", "    pass")
    assert "target_stubbed" not in _codes(diff, ("reduce_incremental",))
