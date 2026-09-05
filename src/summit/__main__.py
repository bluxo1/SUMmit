"""Module entry point so SUMmit runs as ``python -m summit``.

This is a thin shim around the Typer application in :mod:`summit.cli`. All
argument parsing, orchestration, and error handling live there so that the
``summit`` console script and ``python -m summit`` behave identically.
"""

from __future__ import annotations

import sys

from summit.cli import app

#: Shell convention for a process terminated by SIGINT (128 + 2).
_EXIT_SIGINT = 130


def main() -> int:
    """Run the SUMmit CLI and translate interrupts into an exit code.

    Typer/Click already convert a ``KeyboardInterrupt`` raised inside a command
    into ``Abort``. This guard covers the remaining window — an interrupt during
    startup or while Click is tearing down — so the user never sees a traceback,
    per the error-state rules in the design docs.

    Returns:
        The process exit code. ``0`` on success, ``130`` if the user pressed
        Ctrl+C, or whatever code the CLI raised via ``SystemExit``.
    """
    try:
        app()
    except KeyboardInterrupt:
        # Written to stderr directly: importing Rich here would be wasted work
        # on a path where the user has already walked away.
        sys.stderr.write("\nAborted. Nothing was committed.\n")
        return _EXIT_SIGINT
    except SystemExit as exc:
        # Click exits via SystemExit in standalone mode; forward its code.
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        # A string payload means an error message; Python prints it as-is.
        sys.stderr.write(f"{exc.code}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
