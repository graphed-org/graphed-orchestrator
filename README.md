# graphed-orchestrator

The **deterministic orchestrator** for the `graphed` gated three-role pipeline (a state machine,
**not** an LLM). It owns the milestone state machine, runs the mechanical gates, computes stall
signals from git + CI evidence, and makes every escalation/pause decision. Part of the
[`graphed-org`](https://github.com/graphed-org) project; see
[`graphed-project`](https://github.com/graphed-org/graphed-project) for the root guidance and the
authoritative plan.

Status: **M0 spine — bootstrapping.** See `CLAUDE.md` for the distilled Part B specification.
