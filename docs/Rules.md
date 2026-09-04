# SUMmit — Rules & Constraints

## Libraries: Use These
| Library | Purpose |
|---------|---------|
| `typer` | CLI argument parsing and command structure |
| `rich` | Terminal colors, tables, panels, spinners, prompt input |
| `GitPython` | Git repository introspection (fallback to `subprocess` if needed) |
| `ollama` | Local LLM inference |
| `openai` | Cloud LLM API client |
| `pydantic-settings` | Type-safe configuration management |
| `httpx` | Async HTTP for cloud API calls |
| `tomli` / `tomllib` | TOML config file parsing |

## Libraries: Do NOT Use
- **Click** — Use Typer instead (more modern, type-hinted)
- **Colorama / termcolor** — Use Rich instead (more powerful)
- **Inquirer / questionary** — Use Rich.prompt instead (consistent styling)
- **Requests** — Use httpx instead (supports async)
- **Argparse** — Use Typer instead (cleaner code)
- **Any GUI framework** (PyQt, Tkinter, Kivy, Electron) — CLI only

## Code Style Rules
1. **Type hints everywhere**: All functions must have typed arguments and return values
2. **No `print()` statements**: Use `rich.console.Console` for all output
3. **No bare exceptions**: Always catch specific exceptions; use `try/except Exception as e`, never `except:`
4. **No hardcoded paths**: Use `pathlib.Path` for all filesystem operations
5. **No hardcoded secrets**: API keys must come from env vars or config files only
6. **No `os.system()`**: Use `subprocess.run()` with `check=True` for shell commands
7. **Max function length**: 50 lines per function; refactor if longer
8. **Docstrings**: Every public function gets a Google-style docstring

## Error Handling Rules
1. **Fail fast with context**: If `git diff --cached` is empty, show: "No staged changes. Run `git add` first."
2. **LLM unreachable**: If Ollama is not running, show clear setup instructions, then try cloud fallback if configured
3. **Malformed LLM response**: If parser can't extract a valid message, show raw response and ask user to edit manually
4. **Git not a repo**: Exit with code 1 and message: "Not a git repository."
5. **Network timeout**: Cloud calls timeout at 15s; show "LLM timed out, try local model" message
6. **Token limit**: If diff > 12,000 chars, truncate with `[diff truncated]` notice in prompt

## Security Rules
1. **NEVER log or display API keys** — even in debug mode, mask them as `sk-****XXXX`
2. **NEVER include secrets in prompts** — scan diff for patterns like `password=`, `api_key=`, `SECRET=` and redact values before sending to LLM
3. **NEVER auto-commit** — Always require explicit user confirmation
4. **Local-first default**: If no config exists, default to local Ollama; warn before sending code to cloud

## AI Assistant Rules
1. **One file at a time**: When generating code, focus on one module per response unless asked otherwise
2. **No placeholder code**: Never write `pass`, `# TODO`, or `raise NotImplementedError` in delivered code
3. **Test before claiming**: If you write a function, ensure it handles edge cases (empty input, None, exceptions)
4. **Explain then code**: Briefly explain the approach before showing the implementation
5. **Keep it simple**: Prefer readable code over clever one-liners
6. **Python 3.10+ features**: Use `match/case`, `|` union types, and structural pattern matching where appropriate

## Secret Redaction Rules

Before sending any diff to an LLM, apply these regex replacements:

| Pattern | Replacement |
|---------|-------------|
| `(?i)(password|passwd|pwd)\s*=\s*[^\s&]+` | `\1=[REDACTED]` |
| `(?i)(api_key|apikey|api-secret)\s*=\s*[^\s&]+` | `\1=[REDACTED]` |
| `(?i)(secret|token|private_key)\s*=\s*[^\s&]+` | `\1=[REDACTED]` |
| `(?i)Authorization:\s*(Bearer|Basic)\s+[^\s]+` | `Authorization: \1 [REDACTED]` |

- Redaction happens in `git_utils.py` before prompt building
- Never log pre-redaction diff at INFO level or higher
- If >5 secrets found, warn user: "Diff contains sensitive data. Review before sending."

## Logging Rules

- Use `logging` module, not `print()`
- Log file: `~/.local/share/summit/logs/summit.log`
- Rotation: 7 days, max 5MB per file
- Levels:
  - `DEBUG`: Full prompts, API responses
  - `INFO`: Generation start/end, model used, user action
  - `WARNING`: Fallbacks, cache misses, truncated diffs
  - `ERROR`: Exceptions, API failures
- Never log API keys, diffs containing secrets, or full commit messages at INFO+
