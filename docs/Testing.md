# SUMmit — Testing Strategy

## State Machine

```
IDLE -> EXTRACT_DIFF -> BUILD_PROMPT -> CALL_LLM -> PARSE -> DISPLAY -> DECISION
                                           |         |
                                     TIMEOUT    PARSE_FAIL
                                           |         |
                                    RETRY/FALLBACK  MANUAL_EDIT
```

## Unit Tests

### Framework
- **pytest** with `pytest-cov` for coverage
- **Target**: >80% coverage

### Git Utils Tests
- Create fake git repos in `tmp_path` fixtures
- Test `get_staged_diff()` with no staged changes -> raises `NoStagedChangesError`
- Test `get_repo_info()` returns correct (repo_name, branch)
- Test `get_recent_commits()` returns list of strings

### Parser Tests
- Test `extract_message()` with valid LLM output -> returns `CommitMessage`
- Test `extract_message()` with markdown fences -> strips fences
- Test `validate_format()` with good/bad subjects, types, scopes

### Prompt Builder Tests
- Test diff truncation at 12,000 chars
- Test secret redaction regexes
- Test prompt version inclusion

## Integration Tests

### Mock LLM Servers
- Use `responses` or `pytest-httpx` to mock Ollama API (`/api/chat`)
- Use `responses` to mock OpenAI API
- Test timeout behavior (15s limit)

### Config Tests
- Write temp TOML config, verify `Config` model loads correctly
- Test env var override (`SUMMIT_MODEL=codellama`)

## E2E Tests

### CLI Scenarios
- Run `summit` in a temp git repo with staged changes
- Verify exit code 0 on success, non-zero on errors
- Verify `--dry-run` does not call `git commit`
- Verify `--help` shows all flags

### Test Data
Store sample diffs in `tests/fixtures/`:
- `small_diff.txt` — 1 file, 10 lines
- `large_diff.txt` — 20 files, >12k chars
- `binary_diff.txt` — includes binary file changes
- `secret_diff.txt` — includes `password=123` to test redaction

### Expected Outputs
For each fixture, store expected `CommitMessage` JSON to compare against parser output.

## CI Pipeline
1. `pytest` with coverage report
2. `mypy` strict type checking
3. `ruff` lint and format check
4. Test on Python 3.10, 3.11, 3.12
5. Test on Ubuntu, macOS, Windows
