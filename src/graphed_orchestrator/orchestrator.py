"""The deterministic orchestrator (plan Part B).

A state machine, NOT an LLM. It owns the milestone lifecycle, runs the gates, computes stall
signals from evidence, and makes every escalation/pause decision mechanically. Agent self-reports
are advisory only and never enter these decisions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from . import signals
from .gates import can_record_approve, evaluate_iteration
from .integrity import Finding, scan_diff
from .metrics import build_metrics
from .model import (
    Action,
    Budget,
    Decision,
    GateReport,
    IterationEvidence,
    LadderLevel,
    MilestoneRecord,
    Phase,
    SanityReport,
    Thresholds,
)


class PhaseError(RuntimeError):
    """Raised when an operation is attempted from an invalid phase."""


class Orchestrator:
    """Drives one milestone through the B.1 state machine."""

    def __init__(
        self,
        milestone_id: str,
        *,
        budget: Budget | None = None,
        thresholds: Thresholds | None = None,
        implementation_targets: tuple[str, ...] = (),
    ) -> None:
        self.budget = budget or Budget()
        self.thresholds = thresholds or Thresholds()
        self.targets = implementation_targets
        self.record = MilestoneRecord(milestone_id=milestone_id)

    # ---- convenience accessors -------------------------------------------------
    @property
    def phase(self) -> Phase:
        return self.record.phase

    @property
    def paused(self) -> bool:
        return self.record.phase == Phase.PAUSED

    # ---- forward phase transitions ---------------------------------------------
    def start(self) -> None:
        self._require(Phase.PENDING)
        self.record.phase = Phase.DECOMPOSE

    def begin_test_authoring(self) -> None:
        self._require(Phase.DECOMPOSE)
        self.record.phase = Phase.TEST_AUTHORING

    def run_test_sanity(self, report: SanityReport) -> Decision:
        """TEST_SANITY gate. On pass -> FROZEN; on fail -> back to TEST_AUTHORING (B.3 #1)."""
        self._require(Phase.TEST_AUTHORING)
        self.record.phase = Phase.TEST_SANITY
        if report.passed:
            # Stay in TEST_SANITY; freeze() advances to FROZEN/IMPLEMENTING.
            return Decision(Action.ADVANCE, Phase.TEST_SANITY, reason="test sanity passed")
        self.record.phase = Phase.TEST_AUTHORING
        return Decision(
            Action.RETRY_L0,
            Phase.TEST_AUTHORING,
            signals=("test_sanity_failed",),
            ladder_level=LadderLevel.L0,
            reason="vacuous / non-deterministic / uncollectable suite; route back to test-author",
        )

    def freeze(self, freeze_tag: str) -> None:
        """Tag the freeze commit; tests become read-only and we enter IMPLEMENTING (B.1)."""
        if self.record.phase not in (Phase.TEST_AUTHORING, Phase.TEST_SANITY):
            raise PhaseError(f"cannot freeze from {self.record.phase}")
        self.record.freeze_tag = freeze_tag
        self.record.phase = Phase.IMPLEMENTING

    # ---- the implementer loop --------------------------------------------------
    def record_iteration(self, ev: IterationEvidence, *, diff_text: str = "") -> Decision:
        """Ingest one implementer iteration and return the mechanical decision."""
        if self.record.phase != Phase.IMPLEMENTING:
            raise PhaseError(f"record_iteration only valid in IMPLEMENTING (in {self.record.phase})")

        findings = scan_diff(diff_text, implementation_targets=self.targets) if diff_text else []
        ev = self._merge_integrity(ev, findings)
        gates = evaluate_iteration(ev)
        self.record.metrics.append(build_metrics(ev, gates))
        self.record.gates.append(gates)
        history = self.record.metrics

        # 1. Frozen-test tamper (B.5 #7) -> immediate PAUSE + incident.
        if ev.frozen_tests_touched:
            return self._pause("frozen_test_tamper", incident=True)
        # 2. Integrity violation (B.5 #8) -> immediate PAUSE + incident.
        if ev.integrity_findings:
            return self._pause("integrity_violation", incident=True, detail=", ".join(ev.integrity_findings))
        # 3. Budget exceeded (B.5 #6) -> immediate PAUSE.
        if self._budget_exceeded(ev):
            return self._pause("budget_exceeded")
        # 4. Test dispute (B.5 #11) -> TEST_DISPUTE.
        if ev.dispute_filed is not None:
            self.record.phase = Phase.TEST_DISPUTE
            return Decision(
                Action.DISPUTE,
                Phase.TEST_DISPUTE,
                signals=("test_dispute",),
                reason=f"implementer disputes {ev.dispute_filed}",
            )
        # 5. Flaky gate (B.5 #10) -> quarantine; persistence -> PAUSE.
        if signals.flaky_gate(history):
            self.record.quarantine_strikes += 1
            if self.record.quarantine_strikes > self.thresholds.flaky_persist:
                return self._pause("flaky_gate_persistent")
            return Decision(
                Action.QUARANTINE,
                Phase.IMPLEMENTING,
                signals=("flaky_gate",),
                reason="gate flipped on identical tree_hash; quarantined, not counted as progress",
            )
        # 6. Success -> advance to REVIEW.
        if gates.all_green and ev.pass_count == ev.total_tests and ev.total_tests > 0:
            self.record.phase = Phase.REVIEW
            return Decision(Action.ADVANCE, Phase.REVIEW, reason="all gates green; advancing to review")
        # 7. Ladder signals.
        fired: list[str] = []
        skip_l0 = False
        if signals.oscillation(history, self.thresholds):
            fired.append("oscillation")
            skip_l0 = True  # oscillation is serious: L1 -> L2 (B.5 #3)
        if signals.gate_stuck(history, self.thresholds):
            fired.append("gate_stuck")
            skip_l0 = True  # gate-stuck: L1 -> L2 (B.5 #5)
        if signals.no_progress(history, self.thresholds):
            fired.append("no_progress")
        if signals.repeat_failure(history, self.thresholds):
            fired.append("repeat_failure")
        if signals.thrash(history, self.thresholds):
            fired.append("thrash")
        if fired:
            return self._ladder(tuple(fired), skip_l0=skip_l0)
        # 8. Otherwise keep going.
        return Decision(Action.CONTINUE, Phase.IMPLEMENTING, reason="progressing")

    # ---- review ----------------------------------------------------------------
    def review(self, *, approve: bool, gates: GateReport, issue_count: int = 0) -> Decision:
        """Reviewer verdict. APPROVE is only recordable when all gates are green (B.3 #4)."""
        self._require(Phase.REVIEW)
        if approve:
            if not can_record_approve(gates):
                # Reviewer approving on red gates is itself an integrity violation (B.3 #4).
                return self._pause("reviewer_approved_red_gates", incident=True)
            self.record.phase = Phase.DONE
            return Decision(Action.ADVANCE, Phase.DONE, reason="reviewer APPROVE on green gates")

        # REJECT: track convergence (B.5 #9).
        self.record.reject_count += 1
        not_shrinking = (
            self.record.last_issue_count is not None and issue_count >= self.record.last_issue_count
        )
        self.record.last_issue_count = issue_count
        self.record.phase = Phase.IMPLEMENTING
        if self.record.reject_count >= self.thresholds.review_rejects or (
            not_shrinking and self.record.reject_count >= 2
        ):
            sig = ("review_non_convergence",)
            return self._ladder(sig, skip_l0=True, phase=Phase.IMPLEMENTING)
        return Decision(
            Action.RETRY_L0,
            Phase.IMPLEMENTING,
            signals=("review_reject",),
            ladder_level=LadderLevel.L0,
            reason=f"reviewer reject #{self.record.reject_count}; back to implementing",
        )

    # ---- dispute adjudication --------------------------------------------------
    def adjudicate_dispute(self, *, upheld: bool, new_freeze_tag: str | None = None) -> Decision:
        """Adjudicate a filed Test Dispute (B.5). upheld=True => test stands; else corrected."""
        self._require(Phase.TEST_DISPUTE)
        self.record.dispute_count += 1
        if self.record.dispute_count > self.thresholds.max_disputes:
            return self._pause("repeated_disputes")
        if upheld:
            self.record.phase = Phase.IMPLEMENTING
            return Decision(
                Action.CONTINUE,
                Phase.IMPLEMENTING,
                reason="dispute rejected; frozen test upheld; back to implementing",
            )
        # Test corrected: test-author re-freezes at a new tag.
        if new_freeze_tag is not None:
            self.record.freeze_tag = new_freeze_tag
        self.record.phase = Phase.IMPLEMENTING
        return Decision(
            Action.CONTINUE,
            Phase.IMPLEMENTING,
            reason="dispute upheld; frozen suite corrected and re-frozen",
        )

    def resume(self) -> None:
        """Human-only clear of a PAUSE (B.7 L2). No agent path reaches this."""
        if self.record.phase != Phase.PAUSED:
            raise PhaseError("resume only valid from PAUSED")
        self.record.incident = None
        self.record.phase = Phase.IMPLEMENTING

    def abort(self) -> None:
        """Human-only L3 rollback (B.7)."""
        self.record.phase = Phase.ABORTED

    # ---- internals -------------------------------------------------------------
    def _require(self, phase: Phase) -> None:
        if self.record.phase != phase:
            raise PhaseError(f"operation requires phase {phase}, but in {self.record.phase}")

    def _merge_integrity(self, ev: IterationEvidence, findings: Sequence[Finding]) -> IterationEvidence:
        if not findings:
            return ev
        codes = tuple(f.code for f in findings)
        touched = ev.frozen_tests_touched or any(c == "frozen_test_modified" for c in codes)
        return replace(
            ev,
            integrity_findings=ev.integrity_findings + codes,
            frozen_tests_touched=touched,
        )

    def _budget_exceeded(self, ev: IterationEvidence) -> bool:
        b = self.budget
        return bool(
            (b.iterations_cap is not None and ev.iteration_index >= b.iterations_cap)
            or (b.tokens_cap is not None and ev.tokens_spent > b.tokens_cap)
            or (b.wall_clock_cap_s is not None and ev.wall_clock_s > b.wall_clock_cap_s)
        )

    def _ladder(
        self,
        fired: tuple[str, ...],
        *,
        skip_l0: bool,
        phase: Phase | None = None,
    ) -> Decision:
        """Apply the escalation ladder (B.7): L0 retries -> L1 escalate -> L2 PAUSE."""
        if not skip_l0 and self.record.l0_count < self.thresholds.r_retry:
            self.record.l0_count += 1
            return Decision(
                Action.RETRY_L0,
                phase or self.record.phase,
                signals=fired,
                ladder_level=LadderLevel.L0,
                reason=f"L0 retry {self.record.l0_count}/{self.thresholds.r_retry}",
            )
        if not self.record.escalated:
            self.record.escalated = True
            return Decision(
                Action.ESCALATE_L1,
                phase or self.record.phase,
                signals=fired,
                ladder_level=LadderLevel.L1,
                reason="L0 exhausted (or signal forces L1); escalate to stronger model",
            )
        return self._pause("escalation_exhausted", signals=fired)

    def _pause(
        self,
        reason: str,
        *,
        incident: bool = False,
        detail: str = "",
        signals: tuple[str, ...] = (),
    ) -> Decision:
        self.record.phase = Phase.PAUSED
        self.record.incident = f"{reason}: {detail}" if detail else reason
        sig = signals or (reason,)
        return Decision(
            Action.PAUSE,
            Phase.PAUSED,
            signals=sig,
            ladder_level=LadderLevel.L2,
            reason=f"circuit breaker: {self.record.incident}",
            incident=incident,
        )
