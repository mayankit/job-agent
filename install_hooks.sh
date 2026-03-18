#!/usr/bin/env bash
# =============================================================
# install_hooks.sh
#
# Installs the pre-commit security hook into this git repo.
# Run once after cloning: bash install_hooks.sh
# =============================================================
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

HOOKS_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/hooks"
GIT_HOOKS_DIR="$(git rev-parse --git-dir)/hooks"

if [[ ! -d "$GIT_HOOKS_DIR" ]]; then
  echo -e "${RED}Not a git repository. Run: git init${NC}"
  exit 1
fi

# Install pre-commit hook
if [[ -f "$HOOKS_SRC/pre-commit" ]]; then
  cp "$HOOKS_SRC/pre-commit" "$GIT_HOOKS_DIR/pre-commit"
  chmod +x "$GIT_HOOKS_DIR/pre-commit"
  echo -e "${GREEN}${BOLD}✓ pre-commit hook installed${NC}"
  echo "  Path: $GIT_HOOKS_DIR/pre-commit"
else
  echo -e "${RED}hooks/pre-commit not found${NC}"
  exit 1
fi

echo ""
echo "The hook will now scan every commit for:"
echo "  • API keys and secrets"
echo "  • Staged resume / profile / .env files"
echo "  • Personal data (emails, phone numbers)"
echo "  • Application evidence and database files"
echo ""
echo "To bypass in an emergency (use with caution):"
echo "  git commit --no-verify"
echo ""
