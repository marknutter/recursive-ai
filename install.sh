#!/usr/bin/env bash
# Install the RLM skill into Claude Code's skills directory.
# Also sets up Codex integration if requested.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$HOME/.claude/skills/rlm"

echo "Installing RLM..."

# Install the Python package
echo "Installing Python package..."
cd "$SCRIPT_DIR"
uv sync

# Claude Code skill
echo ""
echo "Setting up Claude Code skill..."
mkdir -p "$SKILL_DIR"
ln -sf "$SCRIPT_DIR/skill/SKILL.md" "$SKILL_DIR/SKILL.md"
echo "  Skill installed at: $SKILL_DIR/SKILL.md"

# Codex integration
if [ "${1:-}" = "--codex" ] || [ "${1:-}" = "--all" ]; then
    echo ""
    echo "Setting up Codex integration..."
    CODEX_DIR="$HOME/.codex"
    mkdir -p "$CODEX_DIR"
    ln -sf "$SCRIPT_DIR/codex/AGENTS.md" "$CODEX_DIR/AGENTS.md"
    echo "  Codex agents file installed at: $CODEX_DIR/AGENTS.md"
    echo ""
    echo "  To use with Codex, set these environment variables:"
    echo "    export RLM_PROVIDER=openai"
    echo "    export OPENAI_API_KEY=<your-key>"
fi

echo ""
echo "Done!"
echo ""
echo "  Claude Code:  /rlm \"find security issues\" ./src/"
if [ "${1:-}" = "--codex" ] || [ "${1:-}" = "--all" ]; then
    echo "  Codex:        Follow AGENTS.md instructions with RLM_PROVIDER=openai"
fi
echo ""
echo "  Providers:    uv run rlm providers"
