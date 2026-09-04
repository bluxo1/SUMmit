# SUMmit — Architecture

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Language | Python | >= 3.10 |
| CLI Framework | Typer | ^0.12 |
| Terminal UI | Rich | ^13.0 |
| Git Operations | GitPython | ^3.1 |
| Local LLM | ollama (Python SDK) | ^0.3 |
| Cloud LLM | openai (Python SDK) | ^1.0 |
| Config | pydantic-settings | ^2.0 |
| HTTP (async) | httpx | ^0.27 |
| Packaging | hatchling | latest |

## App Flow

```
IDLE -> EXTRACT_DIFF -> BUILD_PROMPT -> CALL_LLM -> PARSE -> DISPLAY -> DECISION
                                           |         |
                                     TIMEOUT    PARSE_FAIL
                                           |         |
                                    RETRY/FALLBACK  MANUAL_EDIT
```

## Directory Structure

```
summit/
├── pyproject.toml
├── README.md
├── .gitignore
└── src/
    └── summit/
        ├── __init__.py
        ├── __main__.py
        ├── cli.py
        ├── config.py
        ├── git_utils.py
        ├── llm/
        │   ├── __init__.py
        │   ├── local.py
        │   ├── cloud.py
        │   └── prompts.py
        ├── parser.py
        ├── formatter.py
        ├── cache.py
        └── ui.py
```

## Data Flow

1. **CLI Layer** (`cli.py`): Parses arguments, calls orchestrator
2. **Git Layer** (`git_utils.py`): Extracts `git diff --cached`, repo name, branch, recent commits
3. **Context Builder** (`llm/prompts.py`): Assembles prompt with diff + rules + examples + context
4. **LLM Router** (`llm/__init__.py`): Decides local vs cloud based on config and diff size
5. **Response Parser** (`parser.py`): Cleans LLM output, validates Conventional Commit format
6. **UI Layer** (`ui.py`): Displays message with syntax highlighting, handles user input
7. **Git Execution** (`git_utils.py`): Runs `git commit` if user confirms

## Key Design Patterns
- **Strategy Pattern**: LLM providers (local/cloud) implement same interface
- **Template Method**: Prompt building follows fixed structure with variable injection
- **Fail-Fast**: If git repo is invalid or no staged changes, exit immediately with clear error

## Module Interfaces

### git_utils.py
- `get_staged_diff(repo_path: Path) -> str` — Returns raw diff or raises `NoStagedChangesError`
- `get_repo_info() -> tuple[str, str]` — Returns (repo_name, branch_name)
- `get_recent_commits(n: int = 5) -> list[str]` — Returns last n commit messages

### llm/local.py
- `generate(diff: str, model: str, timeout: int = 30) -> str` — Returns raw LLM response
- `is_available() -> bool` — Checks if Ollama server is running

### parser.py
- `extract_message(raw: str) -> CommitMessage` — Parses LLM output into structured object
- `validate_format(msg: CommitMessage) -> bool` — Checks Conventional Commit compliance

## Data Models

```python
class CommitMessage(BaseModel):
    type: str          # feat, fix, docs...
    scope: str | None
    subject: str       # Max 50 chars
    body: str | None   # Max 72 chars per line
    footer: str | None
    breaking: bool

class Config(BaseModel):
    default_model: str = "codellama"
    fallback_model: str | None = None
    max_diff_chars: int = 12000
    auto_commit: bool = False
    language: str = "en"
```

## Error Codes

| Error Code   | Scenario           | User Message                                          | Exit Code |
| ------------ | ------------------ | ----------------------------------------------------- | --------- |
| `SUMMIT-001` | Not a git repo     | "Not a git repository. Run `git init` first."         | 1         |
| `SUMMIT-002` | No staged changes  | "No staged changes. Run `git add <files>` first."     | 2         |
| `SUMMIT-003` | Ollama unreachable | "Ollama not running. Start with `ollama serve`"       | 3         |
| `SUMMIT-004` | LLM timeout        | "Generation timed out after 15s. Try a smaller diff." | 4         |
| `SUMMIT-005` | Malformed response | "AI returned invalid format. Raw output shown below." | 5         |
| `SUMMIT-006` | Config missing     | "No config found. Run `summit --setup` first."        | 6         |

## Prompt Template

The engineered prompt lives in `llm/prompts.py`. It includes:
- Role priming (expert engineer)
- Input context (repo, branch, files changed, recent commits)
- Staged diff (truncated at 12,000 chars)
- Output rules (Conventional Commits, 50/72 rule, imperative mood)
- Few-shot examples
- Security instruction (redact secrets)
- Strict output rule (commit message only, no markdown fences)

## Caching Strategy

- **Key**: SHA256 of `diff + model_name + prompt_version`
- **Location**: `~/.cache/summit/`
- **TTL**: 30 days
- **Invalidation**: Bumped when prompt template changes

## Prompt Versioning

- `PROMPT_VERSION = "1.0.0"` in `llm/prompts.py`
- Included in cache key
- Migration: bump version forces cache miss

## Logging & Observability

- **Level**: INFO default, DEBUG via `--verbose`
- **Location**: `~/.local/share/summit/logs/summit.log`
- **Rotation**: 7 days, max 5MB
- **Privacy**: No diffs or API keys logged
- **Telemetry**: None. No analytics without explicit opt-in.

## Git Hook Integration

- **Hook**: `prepare-commit-msg`
- **Behavior**: Reads staged diff, generates message, writes to `$1` (commit msg file)
- **Conflict**: Appends to existing hook with guard comment `# SUMmit hook start/end`
- **Install**: `summit --hook install` writes hook to `.git/hooks/`

## Secret Redaction

Before sending diff to LLM, scan and redact:
- `password=`, `passwd=`, `pwd=`
- `api_key=`, `apikey=`, `api-secret`
- `SECRET=`, `TOKEN=`, `PRIVATE_KEY`
- `Authorization: Bearer`, `Basic`
- Redaction: replace value with `[REDACTED]`

## Binary File Handling

- Binary files detected via `git diff --cached --numstat` (`-` in add/del columns)
- Binary filenames listed in prompt but diff content omitted
- Never send binary blobs to LLM
