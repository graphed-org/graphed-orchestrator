# Contributing to graphed-orchestrator

This repo is part of the `graphed` project and is governed by the gated three-role pipeline. The
root [`graphed-project/CLAUDE.md`](https://github.com/graphed-org/graphed-project) and the project
plan (`graphed-project-plan-gated.md`, Part B) are authoritative; the plan always wins.

## Integrity rules — NON-NEGOTIABLE (plan A.7 / B.6)

Violations are severe and PAUSE the entire run. **Never**:

- edit, delete, `skip`, `xfail`, or weaken any test under `tests/frozen/**`;
- lower a coverage/benchmark threshold or relax CI gate config;
- stub, mock, or hard-code the specific thing a test verifies;
- leave a named Implementation Target as bare `NotImplementedError`/`pass` while reporting its
  test green;
- blanket-apply `# type: ignore`, `except: pass`, or unjustified `unsafe`.

If you believe a frozen test is wrong, **do not route around it** — file a Test Dispute under
`.graphed/<Mx>/disputes/<test_id>.md` and stop.

This is the one repo whose subject *is* enforcing the above; its own `tests/frozen/orch/` suite
(the B.8 fakers) must stay green and unmodified.

## The pipeline (plan B)

Work flows through three isolated roles coordinated by this orchestrator: **test-author →
implementer → reviewer**, with mechanical gates between. The roles never converse; they hand off
through frozen artifacts. This orchestrator itself is the bootstrap — it is built directly by the
strong/human role (it cannot run through its own pipeline) and is held to the same gates.

## Local gates (run before pushing)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,docs]"
ruff check . && ruff format --check .
mypy
pytest --cov=graphed_orchestrator --cov-branch --cov-report=term-missing   # >=90% line+branch
sphinx-build -W -b html docs docs/_build/html
```

All must be green. CI re-runs them on the plan A.5 matrix; a green local run is necessary but the
CI matrix is the gate of record.

## Commit / PR conventions

- Branch off `main`; no direct commits to `main` for feature work.
- Keep the frozen suite untouched; add coverage-raising tests under `tests/extra/` only.
- PRs tick the Definition-of-Done checklist (plan E.0) honestly — only what is truly green.
