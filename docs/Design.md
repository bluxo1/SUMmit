# SUMmit — Design & Terminal UI

## Philosophy
SUMmit is a developer tool, not a consumer app. The design prioritizes:
1. **Clarity** — Information hierarchy is obvious at a glance
2. **Speed** — Minimal visual noise, keyboard-driven
3. **Trust** — User must always see what the AI is doing
4. **Consistency** — Follows terminal conventions developers already know

## Color Palette

| Token | Hex | Usage |
|-------|-----|-------|
| `primary` | `#00D9A5` | Success, confirmations, main brand accent |
| `secondary` | `#5B8DEF` | Info, links, secondary highlights |
| `warning` | `#FFB800` | Warnings, fallback actions |
| `error` | `#FF4D4D` | Errors, validation failures |
| `muted` | `#6B7280` | Secondary text, borders, timestamps |
| `bg` | `#0F1117` | Terminal background (dark mode default) |
| `fg` | `#E4E4E7` | Primary text |

## Typography

| Element | Style | Font |
|---------|-------|------|
| App header | Bold, primary color | Terminal default (monospace) |
| Commit message | Bold, white | Terminal default |
| Diff preview | Syntax highlighted | Terminal default |
| Labels/keys | Dim, muted color | Terminal default |
| User input | Underlined, secondary | Terminal default |

## UI Components

### 1. Header Banner
```
+-----------------------------------------+
|  SUMmit  v0.1.0                         |
|  AI-powered commit messages             |
+-----------------------------------------+
```
- Rendered with Rich `Panel`
- Primary color border
- Version number in muted text

### 2. Diff Preview Panel
```
+- Staged Changes (3 files) --------------+
|  src/auth/login.py                      |
|  + def validate_token(token: str):      |
|  +     ...                              |
|                                         |
|  tests/test_auth.py                     |
|  + def test_validate_token():           |
+-----------------------------------------+
```
- File names in bold secondary color
- Additions in green (`#00D9A5`)
- Deletions in red (`#FF4D4D`)
- Context lines in muted gray
- Max 20 lines shown; `[...truncated]` if longer

### 3. Message Display Panel
```
+- Suggested Commit Message --------------+
|                                         |
|  feat(auth): add JWT token validation   |
|                                         |
|  Implement token validation in login    |
|  flow using PyJWT library. Adds         |
|  expiry checking and refresh logic.     |
|                                         |
|  [Generated in 1.2s via codellama]      |
+-----------------------------------------+
```
- Subject line in bold white
- Body in normal white
- Metadata (model, time) in muted at bottom

### 4. Action Prompt
```
Use this message? [y]es / [e]dit / [r]egenerate / [q]uit
> _
```
- Prompt in secondary color
- Cursor blinking after `>`
- Single-key response (no Enter required in TUI mode)

### 5. Error States
```
+- Error ---------------------------------+
|  Ollama is not running.                 |
|                                         |
|  Start it with: ollama serve            |
|                                         |
|  Or use cloud fallback:                 |
|  summit --model gpt-4o-mini             |
+-----------------------------------------+
```
- Red border and icon
- Actionable next steps included
- Never show stack traces to users

### 6. Spinner / Loading
```
Analyzing diff with codellama...
```
- Rich `Spinner` with `dots` style
- Primary color
- Hidden immediately when response arrives

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `y` | Accept message and commit |
| `e` | Edit message (opens `$EDITOR`) |
| `r` | Regenerate message |
| `q` / `Ctrl+C` | Quit without committing |
| `Tab` | Switch panes (TUI mode only) |

## Layout Modes

### Compact Mode (Default)
- Single column, stacked panels
- Fits in 80x24 terminal
- Optimized for speed

### Interactive Mode (`--interactive`)
- Two-column layout (diff left, message right)
- Uses full terminal width
- Requires minimum 100x30 terminal

## Animation & Motion
- **No animations** on message display (instant, trustworthy)
- **Subtle spinner** only during LLM call
- **Fade-in** for TUI mode panels (100ms, barely perceptible)
- **No sound effects**

## Accessibility
- All colors must pass WCAG AA against terminal background
- Never rely on color alone (use icons + text)
- Support `NO_COLOR` env var (disable all colors)
- Support `SUMMIT_SIMPLE` env var (disable TUI, plain text only)
