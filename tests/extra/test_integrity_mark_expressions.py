"""A skip mark is flagged wherever it is written, not only as a decorator."""

from __future__ import annotations

import pytest

from graphed_orchestrator import scan_diff

# assembled, so this file's own lines do not trip the scan
SKIP, XFAIL = "mark." + "skip", "x" + "fail"


def _flagged(line: str) -> bool:
    added = line.format(skip=SKIP, xfail=XFAIL)
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
        "    @pytest.{skip}",
        "    pytest.param(1, marks=[pytest.mark.{xfail}(strict=True)]),",
        '    pytest.{xfail}("known")',
    ],
    ids=[
        "param-skipif",
        "param-skip",
        "pytestmark",
        "bare-mark",
        "decorator",
        "bare-decorator",
        "param-xfail-list",
        "imperative-xfail",
    ],
)
def test_a_skip_mark_is_flagged(line: str) -> None:
    assert _flagged(line)


@pytest.mark.parametrize(
    "line",
    [
        '@pytest.mark.parametrize("skipped", [1])',
        "benchmark.skipif_cold = False",
        '"""Use ``pytest.{skip}if`` only for a missing extra."""',
        "    # {skip}if is only for platform gaps",
        "    # the test used to {xfail} on Windows",
        '    """A skip or {xfail} mark is flagged."""',
    ],
    ids=[
        "parametrize",
        "other-attribute",
        "docstring-mark",
        "comment-mark",
        "comment-word",
        "docstring-word",
    ],
)
def test_a_line_naming_no_skip_mark_is_not_flagged(line: str) -> None:
    assert not _flagged(line)
