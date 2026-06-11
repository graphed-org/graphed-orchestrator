graphed-orchestrator
====================

The **deterministic orchestrator** for the ``graphed`` gated three-role pipeline (plan Part B).
A state machine, **not** an LLM: it owns the milestone lifecycle, runs the mechanical gates,
computes stall signals from git + CI evidence, and makes every escalation/pause decision. Agent
self-reports are advisory only.

Start with :doc:`design` for the engineering walkthrough.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   design
   api
   improvements

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
