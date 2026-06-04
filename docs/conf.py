"""Sphinx configuration for graphed-orchestrator."""

from __future__ import annotations

project = "graphed-orchestrator"
author = "graphed-org"
release = "0.0.1"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx.ext.inheritance_diagram",
]

templates_path = ["_templates"]
exclude_patterns = ["_build"]

html_theme = "furo"
html_title = "graphed-orchestrator"

autodoc_default_options = {"members": True, "undoc-members": False}
autodoc_typehints = "description"
intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}

# Warnings are errors in CI (sphinx-build -W); keep the toctree complete.
nitpicky = False
