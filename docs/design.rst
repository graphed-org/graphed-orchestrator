Design
======

The orchestrator decides everything from **evidence** (:class:`~graphed_orchestrator.IterationEvidence`),
never from an agent's prose. This makes every decision a pure function that is fully testable —
the B.8 faker suite drives synthetic evidence and asserts the mechanically-correct response.

State machine
-------------

``PENDING → DECOMPOSE → TEST_AUTHORING → TEST_SANITY → FROZEN → IMPLEMENTING → REVIEW → DONE``,
with side states ``TEST_DISPUTE``, ``PAUSED`` (circuit breaker), and ``ABORTED`` (human-only).

Modules
-------

================================  ===========================================================
Module                            Responsibility
================================  ===========================================================
``model``                         Immutable domain types (phases, evidence, gates, decisions).
``metrics``                       Deterministic metric derivation (plan B.4).
``gates``                         The seven mechanical gates + TEST_SANITY (plan B.3).
``integrity``                     Diff scan against gate-gaming patterns (plan B.6).
``signals``                       Stall-signal detection over metric history (plan B.5).
``orchestrator``                  The state machine that ties it together (plan B.1/B.7).
``store``                         Durable ``.graphed/state.json`` + ``attempts.md`` backing.
================================  ===========================================================

Inheritance
-----------

.. inheritance-diagram:: graphed_orchestrator.model.Phase graphed_orchestrator.model.Action
   :parts: 1
