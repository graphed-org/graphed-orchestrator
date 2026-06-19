# CLAUDE.md — graphed-orchestrator

Defers to the root **`graphed-project/CLAUDE.md`**; the **project plan
(`graphed-project-plan-gated.md`) always wins.** This file distills **Part B** of the plan.

## What this repo is

The **deterministic orchestrator**: a script / state machine, **NOT an LLM**. It owns the milestone
state machine, runs the mechanical gates, computes all stall signals from artifacts (git + CI), and
makes **every** escalation/pause decision. The three agent roles (test-author, implementer,
reviewer) never converse; they hand off through frozen artifacts, and **their self-reports are
advisory only** — the orchestrator grades from evidence, never from an agent's claim.

Agents are invoked only for the five judgment steps: **decompose, author-tests, implement, review,
adjudicate-dispute.**

## State machine (§B.1)

```
PENDING → DECOMPOSE → TEST_AUTHORING → TEST_SANITY → FROZEN → IMPLEMENTING → REVIEW → DONE
side states: TEST_DISPUTE · ESCALATED · PAUSED (circuit breaker) · ABORTED (human-only)
```

The next milestone's pipeline **MUST NOT** start until the current milestone is `DONE`. The
orchestrator checkpoints its own state (milestone, phase, metric history) after **every** transition
so a paused run resumes exactly where it stopped.

## Context isolation (§B.2) — enforce, do not leak

- **test-author** sees: Part A + the milestone Acceptance Contract + public interfaces of merged
  packages. **Not** any implementation of the current milestone.
- **implementer** sees: Part A + Implementation Targets/Guardrails + the **frozen suite
  (read-only)** + `attempts.md` + the latest Reject Report. **Not** the reviewer's private reasoning.
- **reviewer** sees: Part A + Review Focus + the diff + **all** gate artifacts. **Not** a
  back-channel to the implementer except a structured Reject Report.

## Mechanical gates (§B.3) — agents cannot self-grade

- **TEST_SANITY** (once, before FROZEN): (a) suite collects/compiles; (b) **non-vacuity** — fails
  against the stub (a test that passes with no implementation is rejected); (c) **determinism** —
  two stub runs identical; (d) coverage instrumentation wired. Failure routes back to
  TEST_AUTHORING, **not** to the implementer.
- **PER-ITERATION**: `frozen_tests` all pass · `coverage` ≥ 90% line+branch diff coverage on
  new/changed lines, hits from the **frozen** suite (not only `tests/extra/**`) · `lint`
  (ruff + clippy) · `types` (mypy --strict) · `determinism` · `benchmark` (where defined) ·
  `integrity_scan` (§B.6).
- **DETERMINISM**: identical input → byte-identical optimized graph / serialized plan across runs.
- **REVIEW**: the orchestrator **refuses to record an APPROVE while any gate is red** (anti
  rubber-stamp). A reviewer APPROVE on red gates is itself an integrity violation.
- **CI gate (`GateReport.ci`)**: recording **DONE** additionally requires a **confirmed-green CI for
  the exact commit being marked** (`done_ready = all_green and ci is True`). An `in_progress`/queued/
  unknown CI is **not** green, so a milestone can never be marked DONE off an unfinished run.
  Approving while local gates are green but CI is unconfirmed is **not** an integrity incident — the
  milestone simply stays in REVIEW with an `awaiting_ci` signal until CI is verified. `ci.py`
  (`classify`/`is_ci_green`/`wait_for_ci`) computes this from `gh` for a specific SHA; the
  `scripts/confirm_ci.py` CLI is the pure-Python way to block on the pinned commit (no shell loops).

## Iteration metrics + attempt log (§B.4)

Compute from git + CI each iteration: `pass_count`, `fail_set_hash`, `tree_hash` (excluding
`tests/frozen/**`), `diff_lines`, `coverage`, `benchmark_ok`, `lint_ok`, `types_ok`,
`determinism_ok`, `integrity_ok`, `tokens_spent`, `wall_clock`, `iteration_index`. Append one
structured entry per iteration to `.graphed/<Mx>/attempts.md`; summarize old entries to keep it
bounded — it is the memory that survives a context reset and feeds the next implementer.

## Stall signals → responses (§B.5) — the heart of this repo

| # | Signal | Detection | Default threshold | Response |
|---|--------|-----------|-------------------|----------|
| 1 | No progress | `pass_count` not strictly increasing | 3 iters | L0→L1 |
| 2 | Repeat failure | identical `fail_set_hash` | 3 iters | L0→L1 |
| 3 | Oscillation | tree/fail hash cycles (A,B,A,B) | window 6, cycle ≤3 | L1→**L2 PAUSE** |
| 4 | Thrash | `diff_lines`>400 while `pass_count` flat/falling | 2 iters | L0 (smaller scope)→L1 |
| 5 | Gate-stuck | functional green but coverage/bench/determinism red | 3 iters | L1→L2 |
| 6 | Budget exceeded | tokens/wall/iters over cap | per-milestone (Part D) | **L2 PAUSE** now |
| 7 | Frozen-test tamper | any change under `tests/frozen/**` vs freeze tag | 1 | **L2 PAUSE** + incident |
| 8 | Integrity violation | §B.6 scan hit | 1 | **L2 PAUSE** + incident |
| 9 | Review non-convergence | reject count / issue-set not shrinking | 3 rejects | L1→**L2 PAUSE** |
| 10 | Flaky gate | gate flips on identical `tree_hash` | 1 | quarantine, flag, not progress; persists 2 → L2 |
| 11 | Test dispute | implementer files dispute artifact | 1 | → `TEST_DISPUTE` |
| 12 | Unsatisfiable suite | even L1 implementer can't move `pass_count` | after L1 | `TEST_DISPUTE` or **L2 PAUSE** |

**Test Dispute**: implementer writes `.graphed/<Mx>/disputes/<test_id>.md` and stops →
`TEST_DISPUTE` → adjudicator (test-author on a stronger model, or human). Outcomes: **upheld**
(return to IMPLEMENTING with a note) or **corrected** (test-author amends frozen suite, re-runs
TEST_SANITY, re-freezes at a new tag, log records it). >2 disputes on one milestone → L2 PAUSE.

## Integrity scan (§B.6) — mechanical, on every diff

Flag (→ signal #7/#8): edits to `tests/frozen/**`, CI config, or coverage/benchmark threshold
constants; new `skip`/`xfail`/`#[ignore]`/commented-out or tautological asserts (`assert True`,
`assert x == x`); a named Implementation Target left as bare `NotImplementedError`/`todo!()`/`pass`
while its frozen test is reported green; density spikes of `# type: ignore`, `except: pass`,
`unsafe` without an adjacent justification. **Integrity incidents are never auto-retried** — straight
to PAUSE with an incident report, and the **whole pipeline** pauses (not just the milestone).

## Escalation ladder (§B.7)

- **L0 Retry with notes** — fresh implementer context + latest `attempts.md` + last Reject Report;
  may narrow scope. Up to `R_retry` (default 2) before L1.
- **L1 Escalate model** — re-run the failing role on a stronger model, same artifacts. One L1 before
  L2 unless stated.
- **L2 PAUSE (circuit breaker)** — hard stop; write `.graphed/<Mx>/incident.md`; halt ALL coding;
  **requires explicit human resume/abort.** No agent self-clears a PAUSE.
- **L3 Abort/rollback** — human-only, from PAUSED: discard branch, restore to last `DONE` tag,
  archive incident.
- **Global breakers**: project-wide caps on cumulative `tokens_spent` and consecutive PAUSEs
  (default 2) halt the entire run for human review.

## This repo is software — test it (§B.8)

The orchestrator gets its own frozen suite: simulate agent behaviors — a faker making steady
progress; one that oscillates; one that **tampers with frozen tests**; one that stalls; one that
files a dispute; a flaky gate — and assert the correct transition/response for each. **A pipeline
that cannot detect a tampering faker in test must not be used to run real agents.**

## Build / matrix

Per root §A.5: the full OS × arch × CPython {3.11–3.14, 3.14t} matrix; CI green + the §B.8 faker
suite green are this repo's Definition of Done. Keep the orchestrator deterministic — no LLM calls
in the gate/stall/escalation logic itself.

## CI watching utilities

Two complementary tools confirm remote CI for exact pinned commits (never a branch name):
- **`scripts/confirm_ci.py`** (`ci.py: wait_for_ci`) — BLOCKING green/red verdict; what the DONE
  gate uses.
- **`scripts/watch_ci.py`** (`watch.py: watch`) — STREAMING form: one line per workflow run as it
  reaches a terminal state (failure included — silence must never be mistakable for "still
  running"), transient query errors reported, exit 0/1/2 = all-green/failures/timeout. Born from
  a session monitor that failed silently because **zsh does not word-split unquoted parameters**
  (`for spec in $specs` drove one malformed target into `2>/dev/null`); both tools are pure
  Python so a shell can never re-split the targets.

## The pre-commit gate

`python -m graphed_orchestrator.precommit [REPO] [--fast] [--allow-refreeze PREFIX]` — run it in
ANY graphed repo BEFORE every commit (this is the scripted form of the session discipline: TOML/
YAML validity, lint+format+types via **prek** over the repo's `.pre-commit-config.yaml` (ruff +
ruff-format + mypy — the same hooks CI runs, defined once instead of re-rolled here), full pytest
with zero-collected=fail, sphinx -W, and the integrity scan incl. untracked files, with the
modify-vs-new frozen distinction and a loud sanctioned-refreeze path). Exit 0 = commit allowed.
