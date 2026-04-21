# ccnav

A fast fzf picker for Claude Code sessions.  
Browse, preview, and resume past conversations from anywhere.

## Features

- **Cross-project view** — browse every Claude Code session in one picker, not just the current directory
- **Fuzzy search** — filter by prompt, project, branch, or date
- **Rich preview** — duration, idle time, turn count, first and last user message at a glance
- **One-key resume** — press Enter to `cd` into the session's project and run `claude --resume`
- **Zero config** — reads your existing `~/.claude/` data, never modifies anything

## Requirements

- Linux or macOS
- [Claude Code](https://claude.com/claude-code) CLI (`claude` in `PATH`)
- [fzf](https://github.com/junegunn/fzf) 0.31+
- Python 3.10+

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/dongminlee94/ccnav/main/install.sh | bash
```

Files go to `~/.local/share/ccnav/` and a `ccnav` symlink is created in `~/.local/bin/`.

If `ccnav: command not found` after install, add `~/.local/bin` to your `PATH` by appending this line to your shell rc (`~/.zshrc`, `~/.bashrc`):

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Prefer to inspect the installer first? See [install.sh](install.sh).

## Usage

```bash
ccnav
```

| Key | Action |
|---|---|
| ↑ / ↓ (or Ctrl-J / Ctrl-K) | Navigate sessions |
| Enter | Resume the selected session |
| `?` | Toggle preview pane |
| Ctrl-C / Esc | Quit |

Type to fuzzy-search across prompt text, project path, branch, and date.

## How it works

ccnav reads session metadata from `~/.claude/projects/*/*.jsonl` and `~/.claude/history.jsonl`. It extracts the first user message, branch, cwd, timestamps, and turn counts, then pipes a TSV list into `fzf`.

When you press Enter, ccnav `cd`s into the session's original working directory and runs `claude --resume <session_id>`.

ccnav never modifies your Claude Code data.
