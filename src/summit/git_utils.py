"""Git introspection and commit execution for SUMmit.

This module is the only place that talks to git. It extracts the staged diff,
redacts secrets *before* the text can reach an LLM, reports repository context
for the prompt, and executes the commit once the user has confirmed.

Fail-fast is the contract: every error condition raises a :class:`SummitError`
subclass carrying the documented error code and process exit code, so the CLI
layer never has to guess what went wrong.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

logger = logging.getLogger(__name__)

#: Number of recent commits fed to the prompt for tone matching.
DEFAULT_RECENT_COMMITS = 5

#: Redacting more than this many secrets means the user should look before sending.
SECRET_WARN_THRESHOLD = 5

_REDACTED = "[REDACTED]"

#: Secret patterns from the redaction rules, applied to the diff in order.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(password|passwd|pwd)\s*=\s*[^\s&]+"), rf"\1={_REDACTED}"),
    (re.compile(r"(?i)(api_key|apikey|api-secret)\s*=\s*[^\s&]+"), rf"\1={_REDACTED}"),
    (re.compile(r"(?i)(secret|token|private_key)\s*=\s*[^\s&]+"), rf"\1={_REDACTED}"),
    (
        re.compile(r"(?i)Authorization:\s*(Bearer|Basic)\s+\S+"),
        rf"Authorization: \1 {_REDACTED}",
    ),
)


class SummitError(Exception):
    """Base class for every user-facing SUMmit failure.

    Attributes:
        code: Documented error code, e.g. ``SUMMIT-001``.
        hint: Actionable next step shown beneath the message, if any.
        exit_code: Process exit status the CLI should terminate with.
    """

    code: str = "SUMMIT-000"
    exit_code: int = 1

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class NotAGitRepositoryError(SummitError):
    """Raised when the target directory is not inside a git work tree."""

    code = "SUMMIT-001"
    exit_code = 1

    def __init__(self, path: Path) -> None:
        super().__init__(
            f"Not a git repository: {path}",
            hint="Run `git init` first.",
        )
        self.path = path


class NoStagedChangesError(SummitError):
    """Raised when the index holds nothing to describe."""

    code = "SUMMIT-002"
    exit_code = 2

    def __init__(self) -> None:
        super().__init__(
            "No staged changes.",
            hint="Run `git add <files>` first.",
        )


class CommitFailedError(SummitError):
    """Raised when ``git commit`` itself fails (hook rejection, bad signature)."""

    code = "SUMMIT-007"
    exit_code = 7

    def __init__(self, detail: str) -> None:
        super().__init__(
            "git commit failed.",
            hint=detail.strip() or "Run `git commit` manually to see the full error.",
        )


@dataclass(frozen=True, slots=True)
class StagedFile:
    """One entry from ``git diff --cached --numstat``.

    Attributes:
        path: Repository-relative path as reported by git.
        additions: Added line count, or ``None`` for binary files.
        deletions: Removed line count, or ``None`` for binary files.
    """

    path: str
    additions: int | None
    deletions: int | None

    @property
    def is_binary(self) -> bool:
        """Whether git reported this file as binary (``-`` in the numstat columns)."""
        return self.additions is None or self.deletions is None


def redact_secrets(text: str) -> tuple[str, int]:
    """Replace secret-looking values with ``[REDACTED]``.

    Applies the documented redaction patterns for passwords, API keys, generic
    secrets/tokens, and HTTP ``Authorization`` headers. Key names survive so the
    LLM still sees that a credential changed; only the value is destroyed.

    Args:
        text: Raw diff text, possibly containing credentials.

    Returns:
        A ``(redacted_text, count)`` pair where ``count`` is the number of
        substitutions made across all patterns.
    """
    if not text:
        return "", 0

    redacted = text
    total = 0
    for pattern, replacement in _SECRET_PATTERNS:
        redacted, hits = pattern.subn(replacement, redacted)
        total += hits

    if total:
        # Count only -- never the matched values, and never the pre-redaction diff.
        logger.warning("Redacted %d secret-like value(s) from staged diff.", total)
    return redacted, total


def open_repo(repo_path: Path | None = None) -> Repo:
    """Open the git repository containing ``repo_path``.

    Args:
        repo_path: Directory to search from. Defaults to the current directory.
            Parent directories are searched, so subdirectories work.

    Returns:
        The discovered :class:`~git.Repo`.

    Raises:
        NotAGitRepositoryError: If no work tree encloses the path.
    """
    target = (repo_path or Path.cwd()).resolve()
    try:
        return Repo(target, search_parent_directories=True)
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
        raise NotAGitRepositoryError(target) from exc


def get_staged_diff(repo_path: Path | None = None, *, redact: bool = True) -> str:
    """Return the staged diff, with secrets redacted by default.

    Binary blobs never appear: git emits only a ``Binary files ... differ``
    marker for them. Use :func:`get_staged_files` to name them in the prompt.

    Args:
        repo_path: Directory inside the repository. Defaults to the cwd.
        redact: Whether to strip secret values before returning. Only pass
            ``False`` for local inspection that never reaches an LLM.

    Returns:
        The diff text. Never empty, and not truncated -- the prompt builder owns
        the length budget.

    Raises:
        NotAGitRepositoryError: If the path is not in a git work tree.
        NoStagedChangesError: If nothing is staged.
    """
    repo = open_repo(repo_path)
    # --no-ext-diff ignores user difftool config; --no-color keeps the text parseable.
    diff: str = repo.git.diff("--cached", "--no-color", "--no-ext-diff", "-M")

    if not diff.strip():
        raise NoStagedChangesError

    if not redact:
        return diff

    redacted, count = redact_secrets(diff)
    if count > SECRET_WARN_THRESHOLD:
        logger.warning("Diff contains sensitive data. Review before sending.")
    return redacted


def get_staged_files(repo_path: Path | None = None) -> list[StagedFile]:
    """List staged files with their line counts.

    Args:
        repo_path: Directory inside the repository. Defaults to the cwd.

    Returns:
        One :class:`StagedFile` per staged path, in git's order. Empty if
        nothing is staged.

    Raises:
        NotAGitRepositoryError: If the path is not in a git work tree.
    """
    repo = open_repo(repo_path)
    numstat = repo.git.diff("--cached", "--numstat", "--no-color", "--no-ext-diff", "-M")

    files: list[StagedFile] = []
    for line in numstat.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        added, removed, path = parts
        files.append(
            StagedFile(
                path=path.strip(),
                additions=int(added) if added.isdigit() else None,
                deletions=int(removed) if removed.isdigit() else None,
            )
        )
    return files


def get_repo_info(repo_path: Path | None = None) -> tuple[str, str]:
    """Return the repository name and current branch.

    Args:
        repo_path: Directory inside the repository. Defaults to the cwd.

    Returns:
        A ``(repo_name, branch_name)`` pair. ``repo_name`` falls back to the
        git directory name for bare repos. ``branch_name`` is
        ``"HEAD (detached)"`` when no branch is checked out, or the branch that
        an unborn HEAD points at in a fresh repository.

    Raises:
        NotAGitRepositoryError: If the path is not in a git work tree.
    """
    repo = open_repo(repo_path)

    root = repo.working_tree_dir or repo.git_dir
    repo_name = Path(root).name

    try:
        branch = repo.active_branch.name
    except TypeError:
        # Detached HEAD: active_branch raises rather than returning None.
        branch = "HEAD (detached)"
    except ValueError:
        # Unborn HEAD in a repository with no commits yet.
        branch = repo.git.symbolic_ref("--short", "HEAD", with_exceptions=False) or "HEAD"

    return repo_name, branch


def get_recent_commits(n: int = DEFAULT_RECENT_COMMITS, repo_path: Path | None = None) -> list[str]:
    """Return the subject lines of the most recent commits.

    Used as few-shot context so generated messages match the repository's
    existing tone.

    Args:
        n: How many commits to return. Values below 1 yield an empty list.
        repo_path: Directory inside the repository. Defaults to the cwd.

    Returns:
        Up to ``n`` commit subjects, newest first. Empty for a repository with
        no commits.

    Raises:
        NotAGitRepositoryError: If the path is not in a git work tree.
    """
    if n < 1:
        return []

    repo = open_repo(repo_path)
    if not repo.head.is_valid():
        # Fresh repository: no commits to learn from.
        return []

    try:
        log = repo.git.log(f"-{n}", "--pretty=%s", "--no-color")
    except GitCommandError:
        logger.debug("git log failed while collecting recent commits.", exc_info=True)
        return []

    return [line.strip() for line in log.splitlines() if line.strip()]


def commit(message: str, repo_path: Path | None = None) -> str:
    """Create a commit from the staged changes.

    The caller is responsible for obtaining user confirmation first: SUMmit
    never commits on its own.

    Args:
        message: Full commit message, subject and optional body.
        repo_path: Directory inside the repository. Defaults to the cwd.

    Returns:
        The short SHA of the new commit.

    Raises:
        NotAGitRepositoryError: If the path is not in a git work tree.
        NoStagedChangesError: If the index emptied out before committing.
        CommitFailedError: If git rejected the commit, e.g. a failing hook.
    """
    if not message.strip():
        raise CommitFailedError("Refusing to create a commit with an empty message.")

    repo = open_repo(repo_path)
    if not repo.git.diff("--cached", "--name-only").strip():
        raise NoStagedChangesError

    try:
        repo.git.commit("-m", message)
    except GitCommandError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise CommitFailedError(detail) from exc

    sha: str = repo.head.commit.hexsha[:7]
    logger.info("Created commit %s", sha)
    return sha
