Improvements
============

Tracked design improvements and known limitations for ``graphed-orchestrator`` (plan M0 requires
this file in every package).

Current limitations
-------------------

- **Evidence assembly adapters are out of scope here.** This package decides from
  :class:`~graphed_orchestrator.IterationEvidence`; the git/CI adapters that *populate* it live in
  the run harness. The decision core is what carries the B.8 correctness guarantee.
- **Stall thresholds are defaults** (plan B.5 says "tune per project"). They live in
  :class:`~graphed_orchestrator.Thresholds` and are overridable per milestone.

Planned
-------

- A thin ``git``/``codecov`` adapter that builds ``IterationEvidence`` from a real run.
- Persisted global-circuit-breaker state across milestones (cumulative tokens, consecutive pauses).
- Richer ``attempts.md`` summarization to keep the log bounded (plan B.4).
