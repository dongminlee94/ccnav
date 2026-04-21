#!/usr/bin/env bash
# install.sh — install ccnav
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/dongminlee94/ccnav/main/install.sh | bash
#
# Files go to ~/.local/share/ccnav/, a ccnav symlink is placed in ~/.local/bin/.

set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/dongminlee94/ccnav/main"
INSTALL_DIR="$HOME/.local/share/ccnav"
BIN_DIR="$HOME/.local/bin"

echo "==> Installing ccnav"

command -v curl >/dev/null 2>&1 || { echo "error: curl is required." >&2; exit 1; }

mkdir -p "$INSTALL_DIR" "$BIN_DIR"

curl -fsSL "$REPO_RAW/sessions.py" -o "$INSTALL_DIR/sessions.py"
curl -fsSL "$REPO_RAW/ccnav.sh" -o "$INSTALL_DIR/ccnav.sh"
chmod +x "$INSTALL_DIR/ccnav.sh"

ln -sf "$INSTALL_DIR/ccnav.sh" "$BIN_DIR/ccnav"

echo "==> Installed to $BIN_DIR/ccnav"

# Warn about missing runtime dependencies (non-fatal).
missing=()
for cmd in python3 fzf claude; do
  command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
done
if [[ ${#missing[@]} -gt 0 ]]; then
  echo
  echo "!! Missing runtime dependencies: ${missing[*]}"
  echo "   ccnav will not work until these are installed:"
  [[ " ${missing[*]} " == *" python3 "* ]] && echo "   - python3: https://www.python.org/downloads/"
  [[ " ${missing[*]} " == *" fzf "* ]] && echo "   - fzf: https://github.com/junegunn/fzf"
  [[ " ${missing[*]} " == *" claude "* ]] && echo "   - claude: https://claude.com/claude-code"
fi

# Warn if ~/.local/bin is not in PATH.
case ":$PATH:" in
  *":$BIN_DIR:"*)
    echo
    echo "==> Ready. Run: ccnav"
    ;;
  *)
    echo
    echo "!! $BIN_DIR is not in your PATH."
    echo "   Add this to your shell rc (~/.zshrc or ~/.bashrc):"
    echo
    echo '       export PATH="$HOME/.local/bin:$PATH"'
    ;;
esac
