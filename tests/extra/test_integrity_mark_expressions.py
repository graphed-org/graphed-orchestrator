"""A skip mark is flagged wherever it is written, not only as a decorator."""

from __future__ import annotations

import pytest

from graphed_orchestrator import scan_diff

SKIP = "mark." + "skip"  # assembled, so this file's own lines do not trip the scan


def _flagged(line: str) -> bool:
    added = line.format(skip=SKIP)
    diff = f"--- a/tests/extra/test_x.py\n+++ b/tests/extra/test_x.py\n+{added}\n"
    return "skip_or_xfail_added" in {f.code for f in scan_diff(diff)}


@pytest.mark.parametrize(
    "line",
    [
        '    pytest.param(1, marks=pytest.{skip}if(sys.platform == "win32", reason="x")),',
        "    pytest.param(1, marks=pytest.{skip}),",
        'pytestmark = pytest.{skip}if(not HAVE_X, reason="x")',
        '@{skip}if(not HAVE_X, reason="x")',
        '@pytest.{skip}if(not HAVE_X, reason="x")',
    ],
    ids=["param-skipif", "param-skip", "pytestmark", "bare-mark", "decorator"],
)
def test_a_skip_mark_is_flagged(line: str) -> None:
    assert _flagged(line)


@pytest.mark.parametrize(
    "line",
    ['@pytest.mark.parametrize("skipped", [1])', "benchmark.skipif_cold = False"],
    ids=["parametrize", "other-attribute"],
)
def test_a_line_naming_no_skip_mark_is_not_flagged(line: str) -> None:
    assert not _flagged(line)
