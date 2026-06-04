"""Core domain model for the deterministic orchestrator (plan Part B).

These are plain, immutable data carriers. Every decision the orchestrator makes is a pure
function of evidence expressed in these types — never of an agent's self-report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Phase(StrEnum):
    """Milestone state-machine phases (plan B.1)."""

    PENDING = "PENDING"
    DECOMPOSE = "DECOMPOSE"
    TEST_AUTHORING = "TEST_AUTHORING"
    TEST_SANITY = "TEST_SANITY"
    FROZEN = "FROZEN"
    IMPLEMENTING = "IMPLEMENTING"
    REVIEW = "REVIEW"
    DONE = "DONE"
    # side states
    TEST_DISPUTE = "TEST_DISPUTE"
    PAUSED = "PAUSED"
    ABORTED = "ABORTED"


class Action(StrEnum):
    """The orchestrator's response to an iteration or review (plan B.5/B.7)."""

    CONTINUE = "CONTINUE"
    ADVANCE = "ADVANCE"  # all gates green -> move forward (e.g. to REVIEW / DONE)
    RETRY_L0 = "RETRY_L0"  # ladder L0: fresh context + notes
    ESCALATE_L1 = "ESCALATE_L1"  # ladder L1: stronger model
    PAUSE = "PAUSE"  # ladder L2: circuit breaker, human-only resume
    DISPUTE = "DISPUTE"  # implementer filed a frozen-test dispute
    QUARANTINE = "QUARANTINE"  # flaky gate quarantined, not counted as progress


class LadderLevel(StrEnum):
    """Escalation ladder levels (plan B.7)."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


@dataclass(frozen=True)
class Budget:
    """Per-milestone budget caps (plan Part D overrides these defaults)."""

    iterations_cap: int | None = None
    tokens_cap: int | None = None
    wall_clock_cap_s: float | None = None


@dataclass(frozen=True)
class Thresholds:
    """Stall-signal thresholds (plan B.5 defaults; tunable per project)."""

    no_progress: int = 3
    repeat_failure: int = 3
    thrash_diff_lines: int = 400
    thrash_iters: int = 2
    gate_stuck: int = 3
    review_rejects: int = 3
    r_retry: int = 2
    oscillation_window: int = 6
    oscillation_cycle_len: int = 3
    flaky_persist: int = 2
    max_disputes: int = 2


@dataclass(frozen=True)
class IterationEvidence:
    """Everything the orchestrator learns about one implementer iteration.

    In production this is assembled from git + CI artifacts; in tests the fakers synthesize it
    directly. The orchestrator never reads an agent's prose claims — only this.
    """

    iteration_index: int
    pass_count: int
    total_tests: int
    failing_test_ids: tuple[str, ...] = ()
    source_tree_hash: str = ""  # excludes tests/frozen/** (plan B.4 tree_hash)
    diff_lines: int = 0
    coverage_line: float | None = None
    coverage_branch: float | None = None
    coverage_from_frozen: bool = True
    lint_ok: bool | None = None
    types_ok: bool | None = None
    determinism_ok: bool | None = None
    benchmark_ok: bool | None = None  # None => not defined / N/A for this milestone
    frozen_tests_touched: bool = False  # tamper signal (B.5 #7)
    integrity_findings: tuple[str, ...] = ()  # from the B.6 scan
    tokens_spent: int = 0
    wall_clock_s: float = 0.0
    dispute_filed: str | None = None  # test_id of a filed dispute (B.5 #11)


@dataclass(frozen=True)
class GateReport:
    """The seven mechanical gates (plan B.3). True=green, False=red, None=not-run/N-A."""

    frozen_tests: bool | None = None
    coverage: bool | None = None
    lint: bool | None = None
    types: bool | None = None
    determinism: bool | None = None
    benchmark: bool | None = None  # None => N/A (not blocking)
    integrity_scan: bool | None = None

    @property
    def all_green(self) -> bool:
        """A reviewer APPROVE is permitted only when this is True (plan B.3 #4)."""
        blocking = (
            self.frozen_tests,
            self.coverage,
            self.lint,
            self.types,
            self.determinism,
            self.integrity_scan,
        )
        if any(g is not True for g in blocking):
            return False
        # benchmark may be N/A (None); only an explicit False blocks.
        return self.benchmark is not False


@dataclass(frozen=True)
class IterationMetrics:
    """Derived per-iteration metrics persisted to attempts.md (plan B.4)."""

    iteration_index: int
    pass_count: int
    fail_set_hash: str
    tree_hash: str
    diff_lines: int
    coverage_ok: bool
    benchmark_ok: bool | None
    lint_ok: bool | None
    types_ok: bool | None
    determinism_ok: bool | None
    integrity_ok: bool
    tokens_spent: int
    wall_clock_s: float


@dataclass(frozen=True)
class Decision:
    """The orchestrator's mechanical verdict for one event."""

    action: Action
    phase: Phase
    signals: tuple[str, ...] = ()
    ladder_level: LadderLevel | None = None
    reason: str = ""
    incident: bool = False


@dataclass(frozen=True)
class SanityReport:
    """TEST_SANITY gate result (plan B.3 #1)."""

    collects: bool
    non_vacuous: bool  # the suite fails against the empty/stub implementation
    deterministic: bool  # two stub runs identical
    coverage_instrumented: bool

    @property
    def passed(self) -> bool:
        return self.collects and self.non_vacuous and self.deterministic and self.coverage_instrumented


@dataclass
class MilestoneRecord:
    """Mutable per-milestone state the orchestrator checkpoints after every transition."""

    milestone_id: str
    phase: Phase = Phase.PENDING
    freeze_tag: str | None = None
    reject_count: int = 0
    dispute_count: int = 0
    l0_count: int = 0
    escalated: bool = False
    quarantine_strikes: int = 0
    incident: str | None = None
    last_issue_count: int | None = None
    metrics: list[IterationMetrics] = field(default_factory=list)
    gates: list[GateReport] = field(default_factory=list)
