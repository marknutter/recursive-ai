#!/usr/bin/env bash
# Install the RLM skill into Claude Code's skills directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$HOME/.claude/skills/rlm"

echo "Installing RLM skill..."

# Create skills directory
mkdir -p "$SKILL_DIR"

# Symlink the skill file
ln -sf "$SCRIPT_DIR/skill/SKILL.md" "$SKILL_DIR/SKILL.md"

echo "Skill installed at: $SKILL_DIR/SKILL.md"

# Install the Python package in dev mode
echo "Installing Python package..."
cd "$SCRIPT_DIR"
uv sync

echo ""
echo "Done! You can now use /rlm in Claude Code."
echo ""
echo "Usage:"
echo "  /rlm \"find security issues\" ./src/     # Analyze content"
echo "  /rlm \"what do I know about auth?\"       # Recall from memory"
echo "  /rlm remember \"important finding\" --tags \"security\"  # Store to memory"
