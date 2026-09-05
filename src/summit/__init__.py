"""SUMmit — AI-powered git commit messages from staged diffs.

The name is a pun: SUMmarize + comMIT.

This package exposes the version string used by the CLI (``summit --version``),
the packaging backend (``[tool.hatch.version]`` reads ``__version__`` from this
file), and the prompt cache key.
"""

from __future__ import annotations

__version__ = "0.1.0"
"""Single source of truth for the project version.

Hatchling parses this literal at build time, so it must stay a plain string
assignment: no f-strings, no computed values, no imports.
"""

__all__ = ["__version__"]
