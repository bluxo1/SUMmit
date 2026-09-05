"""Terminal output and user interaction.

All SUMmit output goes through the single :data:`console` defined here, so
colour handling, theming, and stream selection stay consistent. Errors and
warnings are written to stderr; everything the user reads as a result goes to
stdout.

Two environment variables change behaviour, per the accessibility rules:

``NO_COLOR``
    Disables all colour and styling.
``SUMMIT_SIMPLE``
    Disables panels and spinners, emitting plain text only. Useful for git hooks
    and CI logs.

Colour is never the only signal: every status line carries a text label or an
ASCII marker as well.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.text import Text
from rich.theme import Theme

from summit import __version__
from summit.git_utils import SummitError
from summit.parser import CommitMessage

#: Palette from the design spec, as a Rich theme.
SUMMIT_THEME: Final = Theme(
    {
        "summit.primary": "#00D9A5",
        "summit.secondary": "#5B8DEF",
        "summit.warning": "#FFB800",
        "summit.error": "#FF4D4D",
        "summit.muted": "#6B7280",
        "summit.subject": "bold #E4E4E7",
        "summit.body": "#E4E4E7",
    }
)

#: Panel width cap so output stays readable in an 80-column terminal.
PANEL_WIDTH: Final = 72


def _no_color() -> bool:
    """Whether colour output is disabled.

    Returns:
        ``True`` if ``NO_COLOR`` is set to any non-empty value.
    """
    return bool(os.environ.get("NO_COLOR"))


def simple_mode() -> bool:
    """Whether to emit plain text instead of panels and spinners.

    Returns:
        ``True`` if ``SUMMIT_SIMPLE`` is set to any non-empty value.
    """
    return bool(os.environ.get("SUMMIT_SIMPLE"))


def _build_console(stderr: bool = False) -> Console:
    """Construct a themed console.

    Args:
        stderr: Whether to write to stderr instead of stdout.

    Returns:
        A console honouring ``NO_COLOR``. Highlighting is off so version numbers
        and paths are not recoloured mid-sentence.
    """
    return Console(
        theme=SUMMIT_THEME,
        stderr=stderr,
        no_color=_no_color(),
        highlight=False,
        soft_wrap=False,
    )


#: Primary output stream for results the user reads.
console: Final = _build_console()

#: Diagnostics stream, kept separate so stdout stays pipeable.
err_console: Final = _build_console(stderr=True)


def show_banner() -> None:
    """Print the application header.

    Suppressed in simple mode, where the banner is pure decoration.
    """
    if simple_mode():
        return

    title = Text.assemble(
        ("SUMmit", "bold summit.primary"),
        ("  ", ""),
        (f"v{__version__}", "summit.muted"),
    )
    subtitle = Text("AI-powered commit messages", style="summit.muted")
    console.print(
        Panel(
            Text.assemble(title, "\n", subtitle),
            border_style="summit.primary",
            width=PANEL_WIDTH,
            padding=(0, 2),
        )
    )


@contextmanager
def thinking(model: str) -> Iterator[None]:
    """Show a spinner while the model generates.

    Falls back to a single plain line in simple mode or when stdout is not a
    terminal, so redirected output stays clean.

    Args:
        model: Model name shown in the status line.

    Yields:
        ``None``, for the duration of the generation call.
    """
    label = f"Analyzing diff with {model}..."

    if simple_mode() or not console.is_terminal:
        console.print(Text(label, style="summit.muted"))
        yield
        return

    with console.status(Text(label, style="summit.primary"), spinner="dots"):
        yield


def show_message(msg: CommitMessage, model: str, elapsed: float) -> None:
    """Display a generated commit message.

    Args:
        msg: The parsed message to show.
        model: Model that produced it.
        elapsed: Generation time in seconds.
    """
    meta = f"Generated in {elapsed:.1f}s via {model}"

    if simple_mode():
        console.print(msg.render())
        console.print(f"[{meta}]", style="summit.muted")
        return

    content = Text(msg.header, style="summit.subject")
    if msg.body:
        content.append("\n\n")
        content.append(msg.body, style="summit.body")
    if msg.footer:
        content.append("\n\n")
        content.append(msg.footer, style="summit.body")
    content.append("\n\n")
    content.append(f"[{meta}]", style="summit.muted")

    console.print(
        Panel(
            content,
            title="Suggested Commit Message",
            title_align="left",
            border_style="summit.primary",
            width=PANEL_WIDTH,
            padding=(1, 2),
        )
    )


def show_warnings(problems: list[str]) -> None:
    """List format problems without blocking the commit.

    Args:
        problems: Messages from :func:`summit.parser.check_format`. An empty
            list prints nothing.
    """
    if not problems:
        return

    err_console.print(Text("! Format warnings:", style="summit.warning"))
    for problem in problems:
        err_console.print(Text(f"  - {problem}", style="summit.muted"))


def show_error(error: SummitError) -> None:
    """Display a failure with its error code and next step.

    Stack traces are never shown: the message and hint are the whole story.

    Args:
        error: The failure to report.
    """
    label = f"[{error.code}] {error.message}"

    if simple_mode():
        err_console.print(Text(f"Error: {label}", style="summit.error"))
        if error.hint:
            err_console.print(Text(error.hint, style="summit.muted"))
        return

    content = Text(error.message, style="summit.error")
    if error.hint:
        content.append("\n\n")
        content.append(error.hint, style="summit.body")

    err_console.print(
        Panel(
            content,
            title=f"Error {error.code}",
            title_align="left",
            border_style="summit.error",
            width=PANEL_WIDTH,
            padding=(1, 2),
        )
    )


def show_raw_response(raw: str) -> None:
    """Show unparseable model output so the user can salvage it.

    Args:
        raw: The model's original response.
    """
    body = raw.strip() or "(empty response)"

    if simple_mode():
        err_console.print("Raw model output:")
        err_console.print(body)
        return

    err_console.print(
        Panel(
            Text(body, style="summit.body"),
            title="Raw model output",
            title_align="left",
            border_style="summit.muted",
            width=PANEL_WIDTH,
            padding=(1, 2),
        )
    )


def confirm_commit(default: bool = True) -> bool:
    """Ask whether to create the commit.

    Declines automatically when stdin is not interactive, since SUMmit must
    never commit without explicit confirmation.

    Args:
        default: Answer applied when the user presses Enter.

    Returns:
        ``True`` if the user accepted the message.
    """
    if not console.is_interactive:
        err_console.print(
            Text(
                "! Not an interactive terminal; skipping commit.",
                style="summit.warning",
            )
        )
        return False

    try:
        return Confirm.ask(
            Text("Use this message?", style="summit.secondary"),
            console=console,
            default=default,
        )
    except (EOFError, KeyboardInterrupt):
        console.print()
        return False


def show_committed(sha: str) -> None:
    """Confirm that a commit was created.

    Args:
        sha: Short SHA of the new commit.
    """
    console.print(Text.assemble(("+ Committed ", "summit.primary"), (sha, "summit.subject")))


def show_dry_run() -> None:
    """Note that no commit was made because of ``--dry-run``."""
    console.print(Text("- Dry run: nothing committed.", style="summit.muted"))


def show_cancelled() -> None:
    """Note that the user declined the message."""
    console.print(Text("- Cancelled: nothing committed.", style="summit.muted"))


def show_info(text: str) -> None:
    """Print a secondary informational line.

    Args:
        text: Message to display.
    """
    console.print(Text(text, style="summit.muted"))


def show_warning(text: str) -> None:
    """Print a standalone warning to stderr.

    Args:
        text: Message to display.
    """
    err_console.print(Text(f"! {text}", style="summit.warning"))
