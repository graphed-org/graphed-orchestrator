"""Integrity scan (plan B.6) — it must catch each gaming pattern."""

from __future__ import annotations

from graphed_orchestrator import scan_diff


def codes(diff: str, **kw: object) -> set[str]:
    return {f.code for f in scan_diff(diff, **kw)}  # type: ignore[arg-type]


def test_clean_diff_has_no_findings() -> None:
    diff = "--- a/src/x.py\n+++ b/src/x.py\n+def f() -> int:\n+    return 1\n"
    assert scan_diff(diff) == []


def test_frozen_test_modification_flagged() -> None:
    diff = "--- a/tests/frozen/m1/test_a.py\n+++ b/tests/frozen/m1/test_a.py\n+    assert foo()\n"
    assert "frozen_test_modified" in codes(diff)


def test_removed_assertion_flagged() -> None:
    diff = "--- a/src/x.py\n+++ b/src/x.py\n-    assert result == expected\n+    pass\n"
    assert "assertion_removed" in codes(diff)


def test_skip_and_xfail_flagged() -> None:
    diff = "--- a/src/x.py\n+++ b/src/x.py\n+    @pytest.mark.skip\n+    @pytest.mark.xfail\n"
    assert "skip_or_xfail_added" in codes(diff)


def test_tautological_assert_flagged() -> None:
    diff = "--- a/src/x.py\n+++ b/src/x.py\n+    assert True\n+    assert x == x\n"
    assert "tautological_assert" in codes(diff)


def test_target_stub_flagged() -> None:
    diff = "--- a/src/x.py\n+++ b/src/x.py\n+def reduce_incremental():\n+    raise NotImplementedError\n"
    assert "target_stubbed" in codes(diff, implementation_targets=("reduce_incremental",))


def test_type_ignore_flood_flagged() -> None:
    body = "".join(f"+    x{i} = y  # type: ignore\n" for i in range(5))
    diff = "--- a/src/x.py\n+++ b/src/x.py\n" + body
    assert "type_ignore_flood" in codes(diff)


def test_except_pass_flood_flagged() -> None:
    diff = "--- a/src/x.py\n+++ b/src/x.py\n+    except Exception: pass\n+    except ValueError: pass\n"
    assert "except_pass_flood" in codes(diff)


def test_unjustified_unsafe_flagged_but_justified_ok() -> None:
    bad = "--- a/src/lib.rs\n+++ b/src/lib.rs\n+    unsafe { ptr.read() }\n"
    good = "--- a/src/lib.rs\n+++ b/src/lib.rs\n+    // SAFETY: ptr is non-null and aligned\n+    unsafe { ptr.read() }\n"
    assert "unjustified_unsafe" in codes(bad)
    assert "unjustified_unsafe" not in codes(good)


def test_ci_config_modification_flagged() -> None:
    diff = "--- a/.github/workflows/ci.yml\n+++ b/.github/workflows/ci.yml\n+      fail_under: 50\n"
    assert "ci_config_modified" in codes(diff)
