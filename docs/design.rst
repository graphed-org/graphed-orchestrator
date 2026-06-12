How graphed-orchestrator works
==============================

``graphed-orchestrator`` is the deterministic referee of the development process itself. The
graphed ecosystem is built by a gated three-role pipeline — a test author, an implementer, and
a reviewer who never converse and hand off only frozen artifacts — and *something* has to
decide, after each iteration, what happens next: accept, retry, escalate, or stop the line.
This package is that something, and the first design decision explains everything else about
it: **the orchestrator is a state machine, not an agent.** Every decision is a pure function
of mechanical *evidence* — gate results, metric history, diff scans — never of anyone's prose.
Pure functions are exhaustively testable; the suite drives synthetic evidence through every
path and asserts the mechanically-correct response.

.. contents::
   :local:
   :depth: 2


The state machine
-----------------

A milestone moves through::

    PENDING → DECOMPOSE → TEST_AUTHORING → TEST_SANITY → FROZEN → IMPLEMENTING → REVIEW → DONE

with side states ``TEST_DISPUTE`` (a frozen test is challenged, with a written dispute — work
stops, the dispute is adjudicated), ``PAUSED`` (the circuit breaker; resume is human-only),
and ``ABORTED``. The next milestone cannot start until the current one is ``DONE``. The two
transitions that carry the philosophy:

* ``TEST_SANITY → FROZEN``: a suite freezes only after it *collects*, is **non-vacuous**
  (fails against the stub for the right reason — a suite that passes before implementation
  tests nothing), runs deterministically twice, and has coverage instrumentation wired.
* ``REVIEW → DONE``: the reviewer may approve **only when every mechanical gate is green** —
  judgment supplements the gates, it never overrides them (``can_record_approve`` enforces
  this ordering).

Evidence in, decision out
-------------------------

Each implementer iteration produces an :class:`~graphed_orchestrator.IterationEvidence` —
gate-by-gate results (frozen tests, diff coverage, lint, types, determinism, benchmark,
integrity), derived :class:`~graphed_orchestrator.IterationMetrics` (pass counts, a hash of
the failing-test set, coverage numbers), and the diff itself. ``evaluate_iteration(evidence,
history, thresholds, budget)`` returns a :class:`~graphed_orchestrator.Decision`: continue,
``RETRY_L0``, ``ESCALATE_L1``, or ``PAUSE``. The function is pure; feeding it the same
evidence always yields the same decision — which is the property that makes the *process*
auditable the same way the *code* is.

Stall signals
~~~~~~~~~~~~~

Progress problems are detected, not felt. Over the metric history (oldest-first), pure
predicates fire signals — among them:

* **no progress**: the pass count has not strictly increased for *k* consecutive iterations;
* **repeat failure**: the *same* failing-test set (by hash) for *k* iterations — the agent is
  circling, not converging;

plus budget exhaustion and oscillation patterns. Detection and response are separated on
purpose: ``signals`` only says *what is true*; the orchestrator owns the mapping to the
escalation ladder — ``L0`` (retry with a fresh context and notes), ``L1`` (a stronger model),
``L2`` (``PAUSE``: the circuit breaker, human-only resume). The ladder encodes a humility
assumption: a stuck iteration is first a *context* problem, then a *capability* problem, and
only then a *process* problem requiring a human.

The integrity scan
~~~~~~~~~~~~~~~~~~

The gates can be gamed; the integrity scan is the mechanical defense, run over the unified
diff of every iteration *in addition to* reviewer judgment. It looks for the specific shapes
of gate-gaming the process bans:

* any modification under ``tests/frozen/`` — the suite is read-only after freeze, full stop;
* CI/gate-config edits (workflow files, coverage config) that would relax thresholds;
* ``skip``/``xfail`` markers appearing in a diff;
* tautological assertions (``assert True``, ``x == x``);
* stub bodies (``NotImplementedError``, ``todo!()``, bare ``pass``/``...``) behind a named
  implementation target while its test reports green.

A hit is not a retry — it routes **straight to PAUSE with a recorded incident**. The premise
is asymmetry: an honest iteration trips none of these; a dishonest one tripping any of them is
disqualifying, not negotiable.

Durable process state
---------------------

``store`` persists the machine durably and human-readably: ``.graphed/state.json`` (per
milestone: phase, freeze tag, gate booleans, metric history, incidents, escalation counts) and
``attempts.md`` (the append-only narrative log each iteration writes). The state file is the
hand-off artifact between roles — and between sessions: any process, human or agent, can read
exactly where a milestone stands and what evidence got it there. The same convention is reused
verbatim by the integration forks, which carry their own ``.graphed/`` records.

The CI watcher
--------------

``watch.py`` (and ``scripts/watch_ci.py``) is the operational tool the verification step runs
on: given ``owner/repo=sha`` pairs, it polls GitHub Actions and **streams one line per
terminal run** — success, failure, or cancellation — exiting 0 only when everything settled
green (distinct exit codes for failures, timeout, and query errors). Two design points born of
field pain: transient API errors are retried but surface a ``QUERY_ERROR`` after a bounded
streak (a watcher that hides its own blindness reports false green), and the tool is plain
Python precisely because its shell-script ancestor silently failed on word-splitting and
masked exit codes. Usage::

    python scripts/watch_ci.py --poll 60 --timeout 2700 \
        graphed-org/graphed-mvp=<sha> graphed-org/graphed-core-mvp=<sha>

The pre-commit gate
-------------------

``python -m graphed_orchestrator.precommit [REPO]`` is the gate a working session runs before
*any* commit, encoding validations that previously lived in (fallible) memory and shell chains:
TOML/YAML parse checks on every config file (regex edits have shipped invalid TOML twice),
ruff + format, mypy where configured, the full pytest run with zero-collected treated as
failure, ``sphinx -W`` where docs exist — and the integrity scan over everything about to be
committed, untracked files included. Exit status is collected per check, never piped, never
chained. Three deliberate nuances: brand-new ``tests/frozen/`` suites are advisory (they are
the test-authoring deliverable) while modifying an existing frozen file is a hard failure;
``--allow-refreeze PREFIX`` sanctions a freeze amendment loudly (the dispute-correction path —
re-tag required); and a repo may exclude named paths from the *shape* scan via
``[tool.graphed_precommit] integrity_exclude`` (the scanner's own source contains the banned
shapes), downgraded to visible advisories, never silenced.

A worked decision
-----------------

The flavor of the test suite, condensed::

    from graphed_orchestrator import evaluate_iteration, Thresholds, Budget, Action

    # three iterations with the SAME failing-test hash -> the repeat-failure signal fires
    history = [metrics(pass_count=40, fail_set_hash="abc")] * 3
    decision = evaluate_iteration(evidence_with(history), thresholds=Thresholds(),
                                  budget=Budget(l0_retries_left=1))
    assert decision.action is Action.RETRY_L0          # first response: fresh context

    # the same situation with the L0 budget spent escalates instead
    decision = evaluate_iteration(evidence_with(history), thresholds=Thresholds(),
                                  budget=Budget(l0_retries_left=0))
    assert decision.action is Action.ESCALATE_L1

Every branch of the policy is pinned this way — synthetic evidence in, asserted action out —
including the ones that should be rare (integrity incidents, dispute filing, the breaker).


Module map
----------

================================  ===========================================================
Module                            Responsibility
================================  ===========================================================
``model``                         Immutable domain types (phases, evidence, gates, decisions).
``metrics``                       Deterministic metric derivation.
``gates``                         The seven mechanical gates + TEST_SANITY.
``integrity``                     Diff scan against gate-gaming patterns.
``signals``                       Stall-signal detection over metric history.
``orchestrator``                  The state machine that ties it together.
``store``                         Durable ``.graphed/state.json`` + ``attempts.md`` backing.
``watch`` / ``ci``                The streaming GitHub Actions watcher.
``precommit``                     The pre-commit gate (below).
================================  ===========================================================

Inheritance
-----------

.. inheritance-diagram:: graphed_orchestrator.model.Phase graphed_orchestrator.model.Action
   :parts: 1


Phase 2 (deliberately not built)
--------------------------------

* **Driving agents directly.** The orchestrator decides and records; invoking
  models/sessions/tools is out of scope by design (it must stay a pure referee).
* **Cross-repo scheduling.** Milestone ordering is enforced per record; a fleet-level
  scheduler over many repositories is future work.
* **Richer CI intelligence** (log triage, flake classification) in the watcher beyond
  terminal-state streaming.

See :doc:`improvements` for the live tracked list.
