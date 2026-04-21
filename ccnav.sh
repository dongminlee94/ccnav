#!/usr/bin/env bash
# Interactive Claude Code session picker.
# Pipes sessions.py --fzf into fzf, then resumes the selected session.

set -euo pipefail

# Exit with a clear message when a required command is missing from PATH.
require() {
  command -v "$1" >/dev/null 2>&1 || { echo "ccnav: required command '$1' not found in PATH" >&2; exit 1; }
}

# Enforce runtime dependencies — fail fast with actionable errors.
require python3
require fzf
require claude

# Resolve symlinks portably (works on Linux and macOS, no readlink -f dependency).
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  # Convert relative symlink targets to absolute paths before the next hop.
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

# Companion Python script that produces the TSV list and preview cards.
LIST_SCRIPT="$SCRIPT_DIR/sessions.py"

# Pipe the TSV into fzf:
#   --with-nth=3..       hide columns 1 (session_id) and 2 (cwd) from display.
#   --no-sort / --reverse  preserve the newest-first order produced by Python.
#   --preview-window     responsive: right pane normally, top pane on narrow (<120 cols) terms.
#   --bind '?:toggle-preview'  let the user hide the preview on demand.
line=$(python3 "$LIST_SCRIPT" --fzf \
  | fzf --delimiter=$'\t' \
        --with-nth=3.. \
        --no-sort \
        --reverse \
        --height=90% \
        --preview="python3 $LIST_SCRIPT --show {1}" \
        --preview-window='right,40%,wrap,<120(up,50%,wrap)' \
        --bind='?:toggle-preview' \
        --header='Claude Code sessions  |  enter: resume  |  ?: toggle preview  |  ctrl-c: quit')

# User cancelled the picker (Ctrl-C / Esc) — nothing selected.
[[ -z "$line" ]] && exit 0

# Extract the hidden columns from the selected line.
sid=$(printf '%s' "$line" | cut -f1)
cwd=$(printf '%s' "$line" | cut -f2)

# Enter the session's original project directory so claude starts there.
[[ -n "$cwd" && -d "$cwd" ]] && cd "$cwd"

# Replace the shell with claude; control returns to the outer shell on exit.
exec claude --resume "$sid"
