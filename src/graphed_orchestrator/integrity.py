"""Integrity scan over a unified diff (plan B.6).

Mechanical defense against weak agents gaming the gates. Any hit is signal #7/#8 and routes
straight to PAUSE with an incident — never auto-retried. Run *in addition to* reviewer judgment.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# Paths whose modification is an immediate integrity incident (frozen suite + gate config).
DEFAULT_PROTECTED_PREFIXES: tuple[str, ...] = ("tests/frozen/",)
DEFAULT_CONFIG_HINTS: tuple[str, ...] = (
    ".github/workflows/",
    "codecov.yml",
    ".codecov.yml",
)

_SKIP_MARKERS = re.compile(
    r"@pytest\.mark\.(skip|xfail)|pytest\.skip\(|#\[ignore\]|#\s*\[ignore\]|\.skip\(|\bxfail\b"
)
_TAUTOLOGY = re.compile(r"assert\s+(True|1\s*==\s*1|(\w+)\s*==\s*\2)\b")
_STUB = re.compile(r"raise\s+NotImplementedError|todo!\(\)|unimplemented!\(\)")
_TYPE_IGNORE = re.compile(r"#\s*type:\s*ignore")
_EXCEPT_PASS = re.compile(r"except[^\n:]*:\s*pass\b|except\b.*:\s*$")
_UNSAFE = re.compile(r"\bunsafe\b")
_JUSTIFIED = re.compile(r"(SAFETY|JUSTIFY|justified|reason:)", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    detail: str


@dataclass(frozen=True)
class _Added:
    path: str
    text: str


@dataclass(frozen=True)
class _Removed:
    path: str
    text: str


def _parse_diff(diff_text: str) -> tuple[list[_Added], list[_Removed], set[str]]:
    """Return added lines, removed lines, and the set of touched file paths."""
    added: list[_Added] = []
    removed: list[_Removed] = []
    touched: set[str] = set()
    current = ""
    for raw in diff_text.splitlines():
        if raw.startswith("+++ "):
            current = _strip_ab(raw[4:].strip())
            if current and current != "/dev/null":
                touched.add(current)
            continue
        if raw.startswith("--- "):
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            added.append(_Added(current, raw[1:]))
        elif raw.startswith("-") and not raw.startswith("---"):
            removed.append(_Removed(current, raw[1:]))
    return added, removed, touched


def _strip_ab(path: str) -> str:
    for prefix in ("a/", "b/"):
        if path.startswith(prefix):
            return path[len(prefix) :]
    return path


def scan_diff(
    diff_text: str,
    *,
    implementation_targets: Sequence[str] = (),
    protected_prefixes: Sequence[str] = DEFAULT_PROTECTED_PREFIXES,
    config_hints: Sequence[str] = DEFAULT_CONFIG_HINTS,
    type_ignore_threshold: int = 3,
    except_pass_threshold: int = 1,
) -> list[Finding]:
    """Scan a unified diff for integrity violations. Empty list => clean."""
    added, removed, touched = _parse_diff(diff_text)
    findings: list[Finding] = []

    # Frozen-test / gate-config tampering (B.5 #7): any +/- line in a protected path.
    for path in sorted(touched):
        if any(path.startswith(p) for p in protected_prefixes):
            findings.append(Finding("frozen_test_modified", path, "edit under a protected/frozen path"))
        elif any(hint in path for hint in config_hints) and (
            any(a.path == path for a in added) or any(r.path == path for r in removed)
        ):
            findings.append(Finding("ci_config_modified", path, "CI / coverage gate config changed"))

    # Removed assertions (weakening a test or check).
    for rem in removed:
        if re.search(r"\bassert\b", rem.text) and not any(
            a.path == rem.path and "assert" in a.text for a in added
        ):
            findings.append(Finding("assertion_removed", rem.path, rem.text.strip()))

    targets = tuple(implementation_targets)
    type_ignore_count = 0
    except_pass_count = 0
    for idx, add in enumerate(added):
        line = add.text
        prev = added[idx - 1].text if idx > 0 and added[idx - 1].path == add.path else ""
        if _SKIP_MARKERS.search(line):
            findings.append(Finding("skip_or_xfail_added", add.path, line.strip()))
        if _TAUTOLOGY.search(line):
            findings.append(Finding("tautological_assert", add.path, line.strip()))
        if _STUB.search(line) and (
            not targets or any(t in line for t in targets) or _names_target(added, targets)
        ):
            findings.append(Finding("target_stubbed", add.path, line.strip()))
        if _TYPE_IGNORE.search(line):
            type_ignore_count += 1
        if re.search(r"except[^\n]*:\s*pass\s*$", line):
            except_pass_count += 1
        if _UNSAFE.search(line) and not (_JUSTIFIED.search(line) or _JUSTIFIED.search(prev)):
            findings.append(Finding("unjustified_unsafe", add.path, line.strip()))

    if type_ignore_count > type_ignore_threshold:
        findings.append(Finding("type_ignore_flood", "<diff>", f"{type_ignore_count} '# type: ignore'"))
    if except_pass_count > except_pass_threshold:
        findings.append(Finding("except_pass_flood", "<diff>", f"{except_pass_count} 'except: pass'"))

    return findings


def _names_target(added: Sequence[_Added], targets: Sequence[str]) -> bool:
    """True if any named Implementation Target appears among the added lines (so a stub body
    nearby is likely the target left unimplemented while its test is reported green)."""
    if not targets:
        return False
    return any(any(t in a.text for t in targets) for a in added)
