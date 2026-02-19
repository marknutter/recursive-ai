#!/usr/bin/env bash
# Install the RLM skill into OpenClaw's skills directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="/opt/homebrew/lib/node_modules/openclaw/skills/rlm"

echo "Installing RLM skill for OpenClaw..."

# Check if we need sudo (skills directory is owned by root)
if [ ! -w "/opt/homebrew/lib/node_modules/openclaw/skills" ]; then
    echo "Note: Skills directory requires sudo access"
    SUDO="sudo"
else
    SUDO=""
fi

# Create skills directory
$SUDO mkdir -p "$SKILL_DIR"

# Copy the OpenClaw skill file
$SUDO cp "$SCRIPT_DIR/skill/SKILL-openclaw.md" "$SKILL_DIR/SKILL.md"

# Create symlink to the rlm CLI so it's accessible
$SUDO ln -sf "$SCRIPT_DIR" "$SKILL_DIR/rlm-src"

# Install the Python package in dev mode
echo "Installing Python package..."
cd "$SCRIPT_DIR"
uv sync

# Make CLI globally accessible
echo "Installing rlm CLI globally..."
uv tool install -e .

echo ""
echo "✅ Done! RLM is now installed for OpenClaw."
echo ""
echo "You can now use:"
echo "  /rlm \"your query\" path/to/code   - Analyze code beyond context window"
echo "  /rlm \"search query\"              - Search persistent memory"
echo "  /rlm remember \"knowledge\"        - Store knowledge for future sessions"
echo ""
echo "MCP tools available in all sessions:"
echo "  rlm_recall - Search memory"
echo "  rlm_remember - Store memories"
echo "  rlm_memory_list - Browse entries"
echo "  rlm_memory_extract - Extract content"
echo "  rlm_forget - Delete entries"
