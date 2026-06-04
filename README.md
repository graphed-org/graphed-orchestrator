# graphed-orchestrator

The **deterministic orchestrator** for the `graphed` gated three-role pipeline (a state machine,
**not** an LLM). It owns the milestone state machine, runs the mechanical gates, computes stall
signals from git + CI evidence, and makes every escalation/pause decision. Part of the
[`graphed-org`](https://github.com/graphed-org) project; see
[`graphed-project`](https://github.com/graphed-org/graphed-project) for the root guidance and the
authoritative plan.

## What it does

Every decision is a pure function of **evidence** (`IterationEvidence`) — never of an agent's
self-report. That makes the whole engine testable: the B.8 faker suite drives synthetic evidence
through a real `Orchestrator` and asserts the mechanically-correct response.

```python
from graphed_orchestrator import Orchestrator, IterationEvidence

o = Orchestrator("M1")
o.start()
o.begin_test_authoring()
# ... TEST_SANITY, freeze ...
decision = o.record_iteration(
    IterationEvidence(
        iteration_index=0, pass_count=5, total_tests=5,
        coverage_line=95, coverage_branch=92,
        lint_ok=True, types_ok=True, determinism_ok=True,
    )
)
# decision.action -> ADVANCE / CONTINUE / RETRY_L0 / ESCALATE_L1 / PAUSE / DISPUTE / QUARANTINE
```

## Implemented (plan Part B)

B.1 state machine · B.3 mechanical gates (incl. TEST_SANITY non-vacuity) · B.4 metrics +
`attempts.md` · B.5 all stall signals → responses · B.6 integrity scan · B.7 escalation ladder
L0→L1→L2(PAUSE) · B.8 faker self-test suite.

## Develop

```bash
pip install -e ".[dev,docs]"
ruff check . && ruff format --check . && mypy
pytest --cov=graphed_orchestrator --cov-branch   # >=90% line+branch
sphinx-build -W -b html docs docs/_build/html
```

Status: **ORCH engine built; B.8 faker suite green locally (41 tests, 97% coverage).** See
`.graphed/state.json` for live milestone state and `CLAUDE.md` for the distilled Part B spec.
