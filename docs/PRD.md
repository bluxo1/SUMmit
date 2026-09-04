# SUMmit — PRD (Project Requirements Document)

## Project Overview
SUMmit is a CLI tool that automatically generates high-quality git commit messages by analyzing staged diffs using local or cloud-based LLMs. The name is a pun: **SUM**marize + c**OMMIT**.

## Target Users
- Software developers who write commits daily
- Teams wanting consistent Conventional Commit formatting
- Developers who prefer local-first AI (privacy-conscious)
- Engineers working in terminal-centric workflows (Vim, VS Code terminal, JetBrains terminal)

## Core Features

### MVP (Must Have)
1. **Diff Scanning**: Read `git diff --cached` from the current repository
2. **Commit Message Generation**: Produce Conventional Commit formatted messages
3. **Local LLM Support**: Primary support via Ollama (Llama 3, CodeLlama, etc.)
4. **Cloud Fallback**: Optional OpenAI/Anthropic fallback for complex diffs
5. **Interactive Confirmation**: Show generated message, allow edit/accept/reject
6. **Git Hook Integration**: Work as `prepare-commit-msg` hook
7. **Dry Run Mode**: Preview message without committing

### Phase 2 (Should Have)
8. **Multi-file Summarization**: Smart aggregation for large commits (>10 files)
9. **Style Learning**: Analyze recent commit history to match team tone
10. **TUI Mode**: Rich terminal UI with diff preview and message selection
11. **Config File**: `.summit.toml` or `pyproject.toml` [tool.summit] section
12. **PR Description Generation**: `summit pr` to generate PR descriptions from branch diffs

### Phase 3 (Nice to Have)
13. **IDE Extensions**: VS Code, JetBrains, Neovim thin wrappers
14. **Commit Message Linting**: Validate generated messages against team rules
15. **Changelog Generation**: `summit changelog` from commit range
16. **Multi-language Support**: Generate messages in languages other than English

## Non-Goals
- Not a GUI application (no Electron, no web dashboard)
- Not an auto-commit tool (always requires user confirmation)
- Not a code review tool (does not judge code quality)
- Not a replacement for `git` itself

## Success Metrics
- Generated messages pass Conventional Commit spec 95%+ of the time
- Average generation time < 3 seconds (local) / < 5 seconds (cloud)
- User accepts message without editing > 70% of the time
- Zero secrets leaked in commit messages

## Performance Budgets

| Metric | Target |
|--------|--------|
| Cold start | < 500ms |
| Local LLM generation | < 3 seconds |
| Cloud LLM generation | < 5 seconds |
| Memory usage | < 100MB |
| Wheel size | < 50KB |

## Rollback Plan

- Each phase is independent; Phase N must not break Phase N-1
- If a release breaks, rollback to previous git tag
- Cache is versioned; old cache ignored on rollback
- Config schema uses defaults for missing keys (forward compatible)
