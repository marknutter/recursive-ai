#!/usr/bin/env bash
# Install the RLM skill into OpenClaw's skills directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Detect OpenClaw skills directory ---
detect_skills_dir() {
    # Environment variable override
    if [ -n "${OPENCLAW_SKILLS_DIR:-}" ]; then
        echo "$OPENCLAW_SKILLS_DIR"
        return
    fi

    # Use npm to locate global packages
    local npm_root
    if npm_root="$(npm root -g 2>/dev/null)" && [ -d "$npm_root/openclaw/skills" ]; then
        echo "$npm_root/openclaw/skills"
        return
    fi

    # Common installation paths (Homebrew Apple Silicon, Homebrew Intel, manual)
    local dir
    for dir in \
        "/opt/homebrew/lib/node_modules/openclaw/skills" \
        "/usr/local/lib/node_modules/openclaw/skills"; do
        if [ -d "$dir" ]; then
            echo "$dir"
            return
        fi
    done

    return 1
}

SKILLS_BASE="$(detect_skills_dir)" || {
    echo "Error: Could not find OpenClaw installation."
    echo "Set OPENCLAW_SKILLS_DIR to your OpenClaw skills directory and try again."
    echo "  Example: OPENCLAW_SKILLS_DIR=/path/to/openclaw/skills ./install-openclaw.sh"
    exit 1
}

SKILL_DIR="$SKILLS_BASE/rlm"

echo "Installing RLM skill for OpenClaw..."
echo "Skills directory: $SKILLS_BASE"

# Create skills directory (try without sudo first)
if mkdir -p "$SKILL_DIR" 2>/dev/null; then
    SUDO=""
else
    echo "Note: Skills directory requires elevated permissions"
    SUDO="sudo"
    $SUDO mkdir -p "$SKILL_DIR"
fi

# Copy the OpenClaw skill file
$SUDO cp "$SCRIPT_DIR/skill/SKILL-openclaw.md" "$SKILL_DIR/SKILL.md"

# Create symlink to the rlm source
# -n prevents following an existing symlink/directory (avoids recursive rlm-src/rlm-src)
$SUDO ln -sfn "$SCRIPT_DIR" "$SKILL_DIR/rlm-src"

# Ensure uv is available
if ! command -v uv &>/dev/null; then
    echo "UV not found. Installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

# Install the Python package in dev mode
echo "Installing Python package..."
cd "$SCRIPT_DIR"
uv sync

# Make CLI globally accessible
echo "Installing rlm CLI globally..."
uv tool install -e .

echo ""
echo "Done! RLM is now installed for OpenClaw."
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
