"""graphed-orchestrator: the deterministic gated-pipeline orchestrator (plan Part B).

A state machine, NOT an LLM. It owns the milestone lifecycle, runs the mechanical gates, computes
stall signals from git+CI evidence, and makes every escalation/pause decision. Agent self-reports
are advisory only.
"""

from __future__ import annotations

from .ci import CiState, ci_state, classify, is_ci_green, wait_for_ci
from .gates import can_record_approve, evaluate_iteration, evaluate_test_sanity
from .integrity import Finding, scan_diff
from .model import (
    Action,
    Budget,
    Decision,
    GateReport,
    IterationEvidence,
    IterationMetrics,
    LadderLevel,
    MilestoneRecord,
    Phase,
    SanityReport,
    Thresholds,
)
from .orchestrator import Orchestrator, PhaseError

__all__ = [
    "Action",
    "Budget",
    "CiState",
    "Decision",
    "Finding",
    "GateReport",
    "IterationEvidence",
    "IterationMetrics",
    "LadderLevel",
    "MilestoneRecord",
    "Orchestrator",
    "Phase",
    "PhaseError",
    "SanityReport",
    "Thresholds",
    "can_record_approve",
    "ci_state",
    "classify",
    "evaluate_iteration",
    "evaluate_test_sanity",
    "is_ci_green",
    "scan_diff",
    "wait_for_ci",
]

__version__ = "0.0.1"
