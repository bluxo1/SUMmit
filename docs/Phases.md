# SUMmit — Development Phases

## Phase 1: Foundation & Core CLI
**Goal**: A working CLI that generates commit messages from staged diffs.

### Tasks
1. Set up project structure (`pyproject.toml`, src layout, entry points)
2. Implement `git_utils.py`: `get_staged_diff()`, `get_repo_info()`, `get_recent_commits()`
3. Implement `llm/prompts.py`: Build the engineered prompt with diff injection
4. Implement `llm/local.py`: Ollama integration with `ollama.chat()`
5. Implement `parser.py`: Extract clean commit message from LLM response
6. Implement `cli.py`: Single `summit` command with `--model`, `--dry-run` flags
7. Implement basic `ui.py`: Display message, ask yes/no with Rich
8. Wire it all together in `__main__.py`

### Deliverable
```bash
$ summit
# -> Reads staged diff
# -> Calls Ollama
# -> Shows message
# -> User types 'y' -> git commit executed
```

### Success Criteria
- Works end-to-end on any git repo with staged changes
- Generates Conventional Commit format 90%+ of the time
- Exits gracefully on all error conditions

---

## Phase 2: Polish & Configuration
**Goal**: Production-ready UX with customization.

### Tasks
1. Implement `config.py`: Load from `~/.config/summit/config.toml` and env vars
2. Add `--config` flag to CLI
3. Implement cloud fallback in `llm/cloud.py`: OpenAI GPT-4o-mini integration
4. Add `summit --setup` wizard: Detect Ollama, suggest models, write config
5. Implement diff truncation for large changes (>12k chars)
6. Add `summit --hook install` to auto-install `prepare-commit-msg` hook
7. Add `--dry-run` and `--clipboard` flags
8. Implement `ui.py` improvements: Syntax-highlighted diff preview, spinner during generation

### Deliverable
```bash
$ summit --setup
# -> Interactive setup wizard
$ summit --model gpt-4o-mini --dry-run
# -> Shows message without committing
```

### Success Criteria
- Config persists between runs
- Cloud fallback works when Ollama is unavailable
- Git hook installs and functions correctly

---

## Phase 3: Intelligence & TUI
**Goal**: Smarter messages and richer terminal interface.

### Tasks
1. Implement style learning: Feed last 10 commits as few-shot examples
2. Implement multi-file summarization: Group related files, avoid listing all
3. Implement TUI mode (`summit --interactive`):
   - Left pane: Diff preview
   - Right pane: 3 message variants to choose from
   - Bottom: Edit box for manual tweaking
4. Add `summit pr` command: Generate PR description from branch diff
5. Implement caching: Cache diff hash -> message to avoid re-generation
6. Add `--language` flag for non-English commit messages
7. Add commit message linting against custom rules

### Deliverable
```bash
$ summit --interactive
# -> Rich TUI with selectable message options
$ summit pr --base main
# -> Generates PR description
```

### Success Criteria
- TUI renders correctly in standard terminals
- Style learning improves message acceptance rate to >75%
- PR description generation is useful and accurate

---

## Phase 4: Ecosystem & Extensions
**Goal**: Integrate with developer workflows beyond the terminal.

### Tasks
1. VS Code extension (thin wrapper calling CLI)
2. JetBrains plugin (thin wrapper calling CLI)
3. Neovim Lua plugin
4. GitHub Action for CI commit message linting
5. `summit changelog` command (generate from commit range)
6. Homebrew formula and PyPI package distribution
7. Comprehensive test suite (>80% coverage)
8. Documentation site (MkDocs)

### Deliverable
- Available on PyPI: `pip install summit-commit`
- Available on Homebrew: `brew install summit`
- IDE extensions in respective marketplaces

### Success Criteria
- Installation is one command
- IDE integrations feel native
- Test suite passes on CI
