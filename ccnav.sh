#!/usr/bin/env bash
# Interactive Claude Code session picker.
# Pipes sessions.py --fzf into fzf, then resumes the selected session.

set -euo pipefail

require() {
  command -v "$1" >/dev/null 2>&1 || { echo "ccnav: required command '$1' not found in PATH" >&2; exit 1; }
}
require python3
require fzf
require claude

# Resolve symlinks portably (works on Linux and macOS, no readlink -f dependency).
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
LIST_SCRIPT="$SCRIPT_DIR/sessions.py"

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

[[ -z "$line" ]] && exit 0

sid=$(printf '%s' "$line" | cut -f1)
cwd=$(printf '%s' "$line" | cut -f2)

[[ -n "$cwd" && -d "$cwd" ]] && cd "$cwd"
exec claude --resume "$sid"
