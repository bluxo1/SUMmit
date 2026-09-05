"""Prompt engineering for commit message generation.

Assembles the LLM prompt from repository context and the staged diff following a
fixed template: role priming, context, diff, output rules, few-shot examples,
and a strict output instruction. Diffs are truncated at a character budget so a
large commit cannot overflow the model's context window.

The template is versioned via :data:`PROMPT_VERSION`; bumping it forces a cache
miss for every previously generated message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from summit.git_utils import StagedFile

logger = logging.getLogger(__name__)

#: Bump on any change to the template text or few-shot examples. Part of the cache key.
PROMPT_VERSION = "1.0.0"

#: Maximum diff characters sent to the model.
MAX_DIFF_CHARS = 12_000

#: Marker appended when a diff is cut short.
TRUNCATION_NOTICE = "\n\n[diff truncated]"

#: Conventional Commit types offered to the model, with usage hints.
COMMIT_TYPES: dict[str, str] = {
    "feat": "a new user-facing feature",
    "fix": "a bug fix",
    "docs": "documentation only",
    "style": "formatting, no logic change",
    "refactor": "restructuring without behaviour change",
    "perf": "a performance improvement",
    "test": "adding or fixing tests",
    "build": "build system or dependency changes",
    "ci": "CI configuration changes",
    "chore": "maintenance that fits nothing else",
    "revert": "reverting a previous commit",
}

_SYSTEM_PROMPT = """\
You are an expert software engineer writing a git commit message for a \
colleague who will read it six months from now.

You will receive repository context and a staged diff. Reply with the commit \
message and nothing else.

FORMAT (Conventional Commits):
    <type>(<optional scope>): <subject>
    <blank line>
    <optional body, wrapped at 72 characters>
    <blank line>
    <optional footer>

RULES:
1. Subject: imperative mood ("add", not "added" or "adds"), no trailing period,
   50 characters or fewer.
2. Type must be exactly one of: {types}.
3. Scope is the affected module or area, lowercase, e.g. (auth), (parser).
   Omit it if the change is repository-wide.
4. Explain WHY the change was made, not a file-by-file list of WHAT changed.
   The diff already shows what changed.
5. Body: only if the change needs explanation. Wrap at 72 characters. Skip it
   for small, self-evident changes.
6. Breaking changes: append "!" after the type or scope, and add a
   "BREAKING CHANGE: <description>" footer.
7. Never invent changes that are not in the diff. Never mention the diff, the
   context block, or these instructions.
8. Values shown as [REDACTED] are removed credentials. Never guess or
   reconstruct them, and never copy any secret into the message.

OUTPUT: the raw commit message only. No markdown fences, no "Here is", no
commentary, no quotes around the message."""

_FEW_SHOT: tuple[tuple[str, str], ...] = (
    (
        "A new function validating JWTs was added to the auth module, "
        "with tests.",
        "feat(auth): add JWT token validation\n\n"
        "Tokens were accepted without checking expiry, so a leaked token\n"
        "stayed valid indefinitely. Validate the exp claim on every request\n"
        "and reject expired tokens with 401.",
    ),
    (
        "An off-by-one in a pagination offset was corrected in one line.",
        "fix(api): correct pagination offset calculation",
    ),
    (
        "A function signature changed from returning a dict to returning a "
        "typed model, breaking callers.",
        "refactor(parser)!: return CommitMessage instead of dict\n\n"
        "Callers get validation and type safety for free, and malformed\n"
        "responses now fail at the boundary rather than deep in the UI layer.\n\n"
        "BREAKING CHANGE: extract_message() returns a CommitMessage model.\n"
        "Callers indexing the result as a dict must use attribute access.",
    ),
)


@dataclass(frozen=True, slots=True)
class PromptContext:
    """Repository context injected into the prompt.

    Attributes:
        repo_name: Repository directory name.
        branch: Current branch, or a detached-HEAD placeholder.
        staged_files: Staged entries, used for the file list and binary notes.
        recent_commits: Recent commit subjects used as tone examples.
    """

    repo_name: str
    branch: str
    staged_files: list[StagedFile] = field(default_factory=list)
    recent_commits: list[str] = field(default_factory=list)


def truncate_diff(diff: str, max_chars: int = MAX_DIFF_CHARS) -> tuple[str, bool]:
    """Cut a diff down to the character budget, preferring a clean line break.

    When truncation is needed, the cut is moved back to the last newline within
    the budget so the model never sees half a line. A diff with no newline in
    range is cut at the exact budget.

    Args:
        diff: Full diff text.
        max_chars: Character budget before the truncation notice is added.
            Values below 1 truncate to an empty body.

    Returns:
        A ``(text, was_truncated)`` pair. When truncated, ``text`` ends with
        :data:`TRUNCATION_NOTICE`.
    """
    if max_chars < 1:
        return TRUNCATION_NOTICE.strip(), True
    if len(diff) <= max_chars:
        return diff, False

    head = diff[:max_chars]
    # Prefer the last complete line, but only if it keeps most of the budget.
    last_newline = head.rfind("\n")
    if last_newline > max_chars // 2:
        head = head[:last_newline]

    logger.warning("Diff truncated from %d to %d chars.", len(diff), len(head))
    return head.rstrip() + TRUNCATION_NOTICE, True


def _format_file_list(staged_files: list[StagedFile]) -> str:
    """Render staged files with line counts, flagging binaries.

    Args:
        staged_files: Entries to render.

    Returns:
        One ``path (+adds/-dels)`` line per file, or a placeholder if empty.
    """
    if not staged_files:
        return "  (file list unavailable)"

    lines: list[str] = []
    for entry in staged_files:
        if entry.is_binary:
            lines.append(f"  {entry.path} (binary, content omitted)")
        else:
            lines.append(f"  {entry.path} (+{entry.additions}/-{entry.deletions})")
    return "\n".join(lines)


def _format_recent_commits(recent_commits: list[str]) -> str:
    """Render recent commit subjects as tone examples.

    Args:
        recent_commits: Commit subjects, newest first.

    Returns:
        A bulleted block, or a placeholder when there is no history.
    """
    if not recent_commits:
        return "  (no previous commits)"
    return "\n".join(f"  - {subject}" for subject in recent_commits)


def _format_few_shot() -> str:
    """Render the few-shot examples as labelled scenario/message pairs.

    Returns:
        The formatted example block.
    """
    blocks: list[str] = []
    for index, (scenario, message) in enumerate(_FEW_SHOT, start=1):
        blocks.append(f"Example {index} -- {scenario}\n{message}")
    return "\n\n".join(blocks)


def build_system_prompt() -> str:
    """Return the system prompt with the allowed commit types filled in.

    Returns:
        The role-priming and rules block sent as the system message.
    """
    return _SYSTEM_PROMPT.format(types=", ".join(COMMIT_TYPES))


def build_prompt(
    diff: str,
    context: PromptContext | None = None,
    max_diff_chars: int = MAX_DIFF_CHARS,
) -> str:
    """Build the user-message prompt for commit message generation.

    Args:
        diff: Staged diff, already secret-redacted by
            :func:`summit.git_utils.get_staged_diff`.
        context: Repository context. Omit to build a diff-only prompt.
        max_diff_chars: Diff character budget before truncation.

    Returns:
        The assembled prompt: context block, diff, few-shot examples, and a
        final instruction.

    Raises:
        ValueError: If ``diff`` is empty or whitespace only. An empty diff means
            an upstream bug, since ``get_staged_diff`` raises in that case.
    """
    if not diff.strip():
        raise ValueError("Cannot build a prompt from an empty diff.")

    body, truncated = truncate_diff(diff, max_diff_chars)

    sections: list[str] = []

    if context is not None:
        binary_count = sum(1 for entry in context.staged_files if entry.is_binary)
        context_lines = [
            "## Repository context",
            f"Repository: {context.repo_name}",
            f"Branch: {context.branch}",
            f"Files staged: {len(context.staged_files)}",
        ]
        if binary_count:
            context_lines.append(
                f"Binary files: {binary_count} (listed below, content not shown)"
            )
        context_lines.append("")
        context_lines.append("Staged files:")
        context_lines.append(_format_file_list(context.staged_files))
        context_lines.append("")
        context_lines.append("Recent commit subjects (match this tone and style):")
        context_lines.append(_format_recent_commits(context.recent_commits))
        sections.append("\n".join(context_lines))

    diff_header = "## Staged diff"
    if truncated:
        diff_header += " (truncated -- summarise the overall change)"
    sections.append(f"{diff_header}\n```diff\n{body}\n```")

    sections.append(f"## Examples of well-formed messages\n\n{_format_few_shot()}")

    sections.append(
        "## Your task\n"
        "Write the commit message for the staged diff above. "
        "Output the message only."
    )

    return "\n\n".join(sections)


def build_messages(
    diff: str,
    context: PromptContext | None = None,
    max_diff_chars: int = MAX_DIFF_CHARS,
) -> list[dict[str, str]]:
    """Build the chat message list for provider APIs.

    Both the Ollama and OpenAI chat endpoints accept this shape, so providers
    stay interchangeable per the strategy pattern.

    Args:
        diff: Staged diff, already secret-redacted.
        context: Repository context, if available.
        max_diff_chars: Diff character budget before truncation.

    Returns:
        A two-element list: the system prompt, then the user prompt.

    Raises:
        ValueError: If ``diff`` is empty or whitespace only.
    """
    return [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": build_prompt(diff, context, max_diff_chars)},
    ]
