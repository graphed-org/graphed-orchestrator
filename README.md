# graphed-orchestrator

The **deterministic orchestrator** for the `graphed` gated three-role pipeline — a state machine,
**not** an LLM. It owns the milestone lifecycle, runs the mechanical gates, computes every stall
signal from git + CI evidence, and makes every escalation/pause decision. Part of the
[`graphed-org`](https://github.com/graphed-org) project; see
[`graphed-project`](https://github.com/graphed-org/graphed-project) for the root guidance and the
authoritative plan (this repo distills **Part B**).

## Why it exists

The graphed ecosystem is built by three agent roles — a **test-author**, an **implementer**, and a
**reviewer** — that never converse and hand off only through frozen artifacts. *Something* has to
decide, after each iteration, what happens next: advance, retry, escalate, or stop the line. That
referee must not itself be an agent. So every decision here is a pure function of mechanical
**evidence** — gate results, metric history, diff scans — never of anyone's prose. Pure functions
are exhaustively testable, which is the whole point: the process becomes auditable the same way the
code is, and an APPROVE on red gates is mechanically impossible rather than merely discouraged.

```python
from graphed_orchestrator import Orchestrator, IterationEvidence

o = Orchestrator("M1")
o.start()                      # PENDING -> DECOMPOSE
o.begin_test_authoring()       # -> TEST_AUTHORING
# ... run_test_sanity(...) then freeze("freeze-M1-0") -> IMPLEMENTING ...
decision = o.record_iteration(
    IterationEvidence(
        iteration_index=0, pass_count=5, total_tests=5,
        coverage_line=95, coverage_branch=92, coverage_from_frozen=True,
        lint_ok=True, types_ok=True, determinism_ok=True,
    ),
    diff_text="...",           # the unified diff, scanned for integrity violations
)
# decision.action -> ADVANCE / CONTINUE / RETRY_L0 / ESCALATE_L1 / PAUSE / DISPUTE / QUARANTINE
```

## What it does

### The milestone state machine (`orchestrator`, `model`)

```
PENDING -> DECOMPOSE -> TEST_AUTHORING -> TEST_SANITY -> FROZEN -> IMPLEMENTING -> REVIEW -> DONE
side states: TEST_DISPUTE  ·  PAUSED (circuit breaker, human-only resume)  ·  ABORTED (human-only)
```

`Orchestrator` drives one milestone through these phases; `model` holds the immutable domain types
(`Phase`, `Action`, `IterationEvidence`, `GateReport`, `IterationMetrics`, `Decision`, `Thresholds`,
`Budget`, `MilestoneRecord`). Two transitions carry the philosophy: a suite freezes only after
TEST_SANITY confirms it collects, is non-vacuous, runs deterministically, and is instrumented; and
`REVIEW -> DONE` is refused while any gate is red — judgment supplements the gates, it never
overrides them. The next milestone cannot start until the current one is `DONE`.

### Mechanical gates (`gates`)

`evaluate_iteration` computes the per-iteration `GateReport` (frozen-tests-all-pass, ≥90%
line+branch diff coverage **with the covering hits coming from the frozen suite**, lint, types,
determinism, optional benchmark, integrity). `evaluate_test_sanity` computes the pre-freeze
non-vacuity/determinism check. `can_record_approve` encodes the anti-rubber-stamp rule:
`done_ready = all_green and ci is True`, so DONE additionally requires a **confirmed-green CI for
the exact commit being marked**.

### Stall signals and the escalation ladder (`signals`, `metrics`)

`metrics` derives the persisted, content-addressed metric row from raw evidence (stable
`fail_set_hash`/`tree_hash` so identical iterations hash identically). `signals` is pure detection
over the metric history — no-progress, repeat-failure, oscillation, thrash, gate-stuck, flaky-gate.
Detection and response are deliberately separated: signals only say *what is true*; the
orchestrator owns the mapping onto the ladder — **L0** retry with a fresh context and notes,
**L1** escalate to a stronger model, **L2 PAUSE** (the circuit breaker; human-only resume). The
ladder encodes a humility assumption: a stuck iteration is first a context problem, then a
capability problem, and only then a process problem needing a human.

### Integrity scan (`integrity`)

`scan_diff` runs over each iteration's unified diff, *in addition to* reviewer judgment, hunting
the specific shapes of gate-gaming the plan bans: any edit under `tests/frozen/**` or CI/coverage
config, injected `skip`/`xfail`/`#[ignore]`, tautological asserts (`assert True`, `x == x`),
removed assertions, a named Implementation Target left as a bare `pass`/`...`/`NotImplementedError`
body, and density floods of `# type: ignore` / `except: pass` / unjustified `unsafe`. A hit is
never auto-retried — it routes **straight to PAUSE with a recorded incident**, and the whole
pipeline pauses, not just the milestone.

### Durable process state (`store`)

`store` persists the machine durably and human-readably: `.graphed/state.json` (per milestone:
phase, freeze tag, gate booleans, metric history, incidents, escalation counts; written with
sorted keys for byte-stable diffs) and an append-only `attempts.md` narrative per iteration. The
state file is the hand-off artifact between roles and between sessions — any process, human or
agent, can read exactly where a milestone stands and what evidence got it there.

### CI confirmation and watching (`ci`, `watch`)

Both work off the **exact pinned SHA**, never a branch name. `ci` (`classify` / `is_ci_green` /
`wait_for_ci`) gives the single blocking green/red verdict the DONE gate uses: a commit's CI is
green only when a run for that SHA has *completed* with conclusion `success` — `in_progress` /
`queued` / no-run-found all count as not-green. `watch` is the event-stream companion: it polls
many `(repo, sha)` targets together and emits one line per workflow run as it reaches a terminal
state (failure included — silence must never be mistakable for "still running"), surfacing
transient `QUERY_ERROR`s rather than hiding its own blindness. Both are pure Python on purpose:
their shell-script ancestor silently failed because **zsh does not word-split unquoted parameters**,
driving malformed targets into `2>/dev/null`. CLIs: `scripts/confirm_ci.py` (blocking) and
`scripts/watch_ci.py` (streaming); `scripts/advance.py` dogfoods this repo's own ORCH/M0 milestones
through the same decision path.

### The pre-commit gate (`precommit`)

```bash
python -m graphed_orchestrator.precommit [REPO] [--fast] [--no-docs] [--no-types] [--no-coverage] [--allow-refreeze PREFIX]
```

Run it in **any** graphed repo before every commit — the scripted form of the session discipline.
It collects each check's exit status honestly (no pipes, no chains that swallow a failure):
TOML/YAML validity, lint + format + types via **prek** over the repo's `.pre-commit-config.yaml`
(ruff + ruff-format + mypy — the same hooks CI runs, defined once instead of re-rolled here),
the coverage run using the repo's *own* CI `--cov` command read from its workflow (so local can
never green while CI goes red), `sphinx -W` where docs exist, and the integrity scan over
everything about to be committed (untracked files included). It distinguishes a brand-new frozen
suite (the legitimate test-authoring deliverable, advisory) from **modifying** an existing frozen
file (a hard failure), with a loud sanctioned-refreeze path (`--allow-refreeze`). Exit 0 = commit
allowed.

## This repo is software — it tests itself (plan B.8)

The orchestrator carries its own frozen suite under `tests/frozen/orch/` (56 tests). `fakers.py`
simulates agent behaviors — a faker making steady progress, one that oscillates, one that **tampers
with frozen tests**, one that stalls, one that files a dispute, a flaky gate — and the suite drives
that synthetic evidence through a *real* `Orchestrator`, asserting the mechanically-correct
transition for each. *A pipeline that cannot detect a tampering faker in test must not be used to
run real agents.* Additional coverage lives in `tests/extra/` (the pre-commit gate and the CI
watcher). The whole suite is green locally (98 passed, 1 skipped).

## Develop

```bash
pip install -e ".[dev,docs]"
python -m graphed_orchestrator.precommit .          # the one-command gate (run before every commit)
# or the individual checks it wraps:
prek run --all-files                                 # ruff + ruff-format + mypy, as CI runs them
pytest                                               # the frozen + extra suites
sphinx-build -W -b html docs docs/_build/html        # zero-warning docs
```

The API reference at `docs/api.rst` is generated automatically from the package source by
`sphinx.ext.autosummary` (one page per module under `docs/generated/`, gitignored), so it always
reflects the current public API and cannot drift. See `docs/design.rst` for the engineering
walkthrough and `CLAUDE.md` for the distilled Part B spec; `.graphed/state.json` holds the live
milestone state.
