"""Parse and validate LLM output into a structured commit message.

Models are instructed to emit a bare Conventional Commit, but they routinely add
markdown fences, a "Here is the commit message:" preamble, or surrounding
quotes. This module strips that packaging, splits the result into header, body,
and footer, and validates the parts against the Conventional Commits spec.

Parsing and validation are separate steps on purpose: a message that parses but
violates the 50-character subject rule is still usable, so the UI can warn
without blocking the commit.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field, field_validator

from summit.git_utils import SummitError
from summit.llm.prompts import COMMIT_TYPES

logger = logging.getLogger(__name__)

#: Conventional Commits recommends 50 characters for the subject line.
MAX_SUBJECT_LENGTH = 50

#: Hard ceiling before git tooling starts truncating in logs.
SUBJECT_TRUNCATE_LENGTH = 72

#: Recommended wrap width for body lines.
MAX_BODY_LINE_LENGTH = 72

#: Matches a Conventional Commit header: type(scope)!: subject
_HEADER_RE = re.compile(
    r"""
    ^\s*
    (?P<type>[A-Za-z]+)                 # type: feat, fix, ...
    \s*
    (?:\(\s*(?P<scope>[^)]*?)\s*\))?    # optional (scope)
    (?P<breaking>\s*!)?                 # optional ! for breaking change
    \s*:\s*
    (?P<subject>\S.*?)                  # subject, at least one non-space char
    \s*$
    """,
    re.VERBOSE,
)

#: Matches a git trailer line, e.g. "Closes: #12" or "BREAKING CHANGE: ...".
_TRAILER_RE = re.compile(
    r"^(BREAKING[ -]CHANGE|[A-Z][A-Za-z-]*)\s*:\s*\S|^BREAKING[ -]CHANGE\s*:",
)

#: Fenced code block, with or without a language tag, anywhere in the response.
_FENCE_BLOCK_RE = re.compile(r"```[A-Za-z0-9_+-]*\s*\n(?P<inner>.*?)\n?```", re.DOTALL)

#: A stray opening or closing fence left after block extraction.
_LOOSE_FENCE_RE = re.compile(r"^\s*```[A-Za-z0-9_+-]*\s*$", re.MULTILINE)

#: Conversational preambles models prepend despite instructions.
_PREAMBLE_RE = re.compile(
    # Every literal space is written as \s+ or \s*: re.VERBOSE strips unescaped
    # whitespace from the pattern, so a literal " is" would match "is".
    r"""
    ^\s*
    (?:
        (?:here(?:'s|\s+is)|this\s+is|below\s+is)\s+
        (?:the\s+|a\s+|my\s+)?
        (?:suggested\s+|proposed\s+|generated\s+)?
        commit\s+message
      | (?:suggested\s+|proposed\s+|generated\s+)?commit\s+message
      | message
      | output
      | answer
    )
    \s*[:\-]*
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: Trailing chatter models append after the message.
_EPILOGUE_RE = re.compile(
    r"^\s*(?:let me know|hope this helps|feel free|is this|does this|note:)",
    re.IGNORECASE,
)


class MalformedResponseError(SummitError):
    """Raised when no Conventional Commit header can be found in the output."""

    code = "SUMMIT-005"
    exit_code = 5

    def __init__(self, raw: str) -> None:
        super().__init__(
            "AI returned invalid format.",
            hint="Edit the message manually, or retry with `--model <name>`.",
        )
        self.raw = raw


class CommitMessage(BaseModel):
    """A parsed Conventional Commit message.

    Attributes:
        type: Commit type, lowercased, e.g. ``feat``.
        scope: Affected area, or ``None`` when repository-wide.
        subject: Imperative summary line, without the type prefix.
        body: Explanatory paragraphs, or ``None``.
        footer: Git trailers such as ``BREAKING CHANGE:``, or ``None``.
        breaking: Whether this is a breaking change.
    """

    type: str
    scope: str | None = None
    subject: str = Field(min_length=1)
    body: str | None = None
    footer: str | None = None
    breaking: bool = False

    @field_validator("type")
    @classmethod
    def _normalise_type(cls, value: str) -> str:
        """Lowercase and strip the commit type."""
        return value.strip().lower()

    @field_validator("scope", "body", "footer")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        """Collapse empty or whitespace-only optional fields to ``None``."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("subject")
    @classmethod
    def _clean_subject(cls, value: str) -> str:
        """Strip whitespace and any trailing period from the subject."""
        return value.strip().rstrip(".").strip()

    @property
    def header(self) -> str:
        """The first line of the commit message, reassembled."""
        scope = f"({self.scope})" if self.scope else ""
        bang = "!" if self.breaking else ""
        return f"{self.type}{scope}{bang}: {self.subject}"

    def render(self) -> str:
        """Render the full commit message for ``git commit``.

        Returns:
            Header, body, and footer joined by blank lines, with no trailing
            newline.
        """
        parts = [self.header]
        if self.body:
            parts.append(self.body)
        if self.footer:
            parts.append(self.footer)
        return "\n\n".join(parts)

    def __str__(self) -> str:
        """Return the rendered commit message."""
        return self.render()


def strip_packaging(raw: str) -> str:
    """Remove markdown fences, preambles, epilogues, and wrapping quotes.

    Args:
        raw: Unmodified model output.

    Returns:
        The candidate commit message text. Empty if nothing survives.
    """
    text = raw.strip()
    if not text:
        return ""

    # Prefer the contents of a fenced block: models often wrap the message and
    # leave their commentary outside the fence.
    fenced = _FENCE_BLOCK_RE.search(text)
    if fenced:
        inner = fenced.group("inner").strip()
        if inner:
            text = inner
    else:
        text = _LOOSE_FENCE_RE.sub("", text).strip()

    lines = text.splitlines()

    # Drop leading conversational lines and any blank lines they leave behind.
    while lines and (not lines[0].strip() or _PREAMBLE_RE.match(lines[0])):
        lines.pop(0)

    # Drop trailing chatter and blank lines.
    while lines and (not lines[-1].strip() or _EPILOGUE_RE.match(lines[-1])):
        lines.pop()

    text = "\n".join(lines).strip()
    return _strip_wrapping_quotes(text)


def _strip_wrapping_quotes(text: str) -> str:
    """Remove a single matched pair of quotes around the whole message.

    Args:
        text: Candidate message text.

    Returns:
        The text without symmetric wrapping quotes.
    """
    for quote in ('"""', "'''", '"', "'", "`"):
        if len(text) > 2 * len(quote) and text.startswith(quote) and text.endswith(quote):
            return text[len(quote) : -len(quote)].strip()
    return text


def _split_sections(lines: list[str]) -> tuple[str | None, str | None]:
    """Split post-header lines into body and footer.

    The footer is the final paragraph when every one of its lines reads as a git
    trailer, e.g. ``BREAKING CHANGE: ...`` or ``Closes: #12``.

    Args:
        lines: Lines following the header, leading blanks already removed.

    Returns:
        A ``(body, footer)`` pair, either of which may be ``None``.
    """
    text = "\n".join(lines).strip()
    if not text:
        return None, None

    paragraphs = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if not paragraphs:
        return None, None

    last = paragraphs[-1]
    is_trailer_block = all(_TRAILER_RE.match(line.strip()) for line in last.splitlines())

    if is_trailer_block and len(paragraphs) > 1:
        return "\n\n".join(paragraphs[:-1]), last
    if is_trailer_block:
        return None, last
    return "\n\n".join(paragraphs), None


def extract_message(raw: str) -> CommitMessage:
    """Parse raw model output into a :class:`CommitMessage`.

    Args:
        raw: Model output, possibly wrapped in fences or commentary.

    Returns:
        The parsed message. Validation of style rules is
        :func:`validate_format`'s job.

    Raises:
        MalformedResponseError: If no line contains a Conventional Commit
            header, or the output is empty.
    """
    cleaned = strip_packaging(raw)
    if not cleaned:
        raise MalformedResponseError(raw)

    lines = cleaned.splitlines()

    # Scan for the header: leftover chatter may still precede it.
    for index, line in enumerate(lines):
        match = _HEADER_RE.match(line)
        if not match:
            continue

        rest = lines[index + 1 :]
        while rest and not rest[0].strip():
            rest.pop(0)
        body, footer = _split_sections(rest)

        breaking = bool(match.group("breaking")) or bool(
            footer and re.search(r"BREAKING[ -]CHANGE", footer)
        )
        return CommitMessage(
            type=match.group("type"),
            scope=match.group("scope"),
            subject=match.group("subject"),
            body=body,
            footer=footer,
            breaking=breaking,
        )

    logger.warning("No Conventional Commit header found in model output.")
    raise MalformedResponseError(raw)


def check_format(msg: CommitMessage) -> list[str]:
    """Collect Conventional Commit style violations.

    Args:
        msg: Parsed message to inspect.

    Returns:
        Human-readable problems, empty when the message is fully compliant.
    """
    problems: list[str] = []

    if msg.type not in COMMIT_TYPES:
        allowed = ", ".join(COMMIT_TYPES)
        problems.append(f"Unknown type {msg.type!r}. Expected one of: {allowed}.")

    if len(msg.subject) > MAX_SUBJECT_LENGTH:
        problems.append(
            f"Subject is {len(msg.subject)} characters; "
            f"{MAX_SUBJECT_LENGTH} or fewer is recommended."
        )

    if msg.subject.endswith("."):
        problems.append("Subject should not end with a period.")

    if msg.subject[:1].isupper() and not msg.subject.split(" ", 1)[0].isupper():
        problems.append("Subject should start lowercase (imperative mood).")

    if msg.scope is not None:
        if not msg.scope:
            problems.append("Scope is present but empty.")
        elif msg.scope != msg.scope.lower():
            problems.append(f"Scope {msg.scope!r} should be lowercase.")

    if msg.body:
        long_lines = [
            number
            for number, line in enumerate(msg.body.splitlines(), start=1)
            if len(line) > MAX_BODY_LINE_LENGTH
        ]
        if long_lines:
            listed = ", ".join(str(number) for number in long_lines[:5])
            problems.append(
                f"Body line(s) {listed} exceed {MAX_BODY_LINE_LENGTH} characters."
            )

    if msg.breaking and not (msg.footer and re.search(r"BREAKING[ -]CHANGE", msg.footer)):
        problems.append("Breaking change is missing a 'BREAKING CHANGE:' footer.")

    return problems


def validate_format(msg: CommitMessage) -> bool:
    """Report whether a message satisfies the Conventional Commits rules.

    Args:
        msg: Parsed message to check.

    Returns:
        ``True`` when :func:`check_format` finds no problems.
    """
    problems = check_format(msg)
    if problems:
        logger.debug("Commit message has %d format issue(s).", len(problems))
    return not problems
