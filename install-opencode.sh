#!/usr/bin/env bash
# Install the RLM plugin for OpenCode.
#
# Three steps:
# 1. uv sync (Python dependencies)
# 2. Copy plugin to ~/.config/opencode/plugins/ with RLM_ROOT substituted
# 3. Register MCP server in ~/.config/opencode/opencode.json
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPENCODE_CONFIG_DIR="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}"
PLUGINS_DIR="$OPENCODE_CONFIG_DIR/plugins"
CONFIG_FILE="$OPENCODE_CONFIG_DIR/opencode.json"

echo "Installing RLM for OpenCode..."
echo "  RLM root: $SCRIPT_DIR"
echo "  Config:   $OPENCODE_CONFIG_DIR"

# --- Step 1: Python dependencies ---
if ! command -v uv &>/dev/null; then
    echo "uv not found. Installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

echo ""
echo "Step 1/3: Installing Python dependencies..."
cd "$SCRIPT_DIR"
uv sync

# --- Step 2: Install plugin ---
echo ""
echo "Step 2/3: Installing OpenCode plugin..."
mkdir -p "$PLUGINS_DIR"

# Copy plugin with __RLM_ROOT__ substituted
sed "s|__RLM_ROOT__|${SCRIPT_DIR}|g" \
    "$SCRIPT_DIR/opencode/rlm-plugin.ts" \
    > "$PLUGINS_DIR/rlm-plugin.ts"

echo "  Plugin installed: $PLUGINS_DIR/rlm-plugin.ts"

# --- Step 3: Register MCP server ---
echo ""
echo "Step 3/3: Registering MCP server..."

# Create config file if it doesn't exist
if [ ! -f "$CONFIG_FILE" ]; then
    echo '{}' > "$CONFIG_FILE"
fi

# Check if jq is available for JSON manipulation
if command -v jq &>/dev/null; then
    # Use jq to merge MCP config
    MCP_CONFIG=$(jq -n \
        --arg project "$SCRIPT_DIR" \
        '{
            mcp: {
                rlm: {
                    type: "local",
                    command: ["uv", "run", "--project", $project, "python", "mcp/server.py"]
                }
            }
        }')

    # Merge into existing config (preserving other settings)
    jq -s '.[0] * .[1]' "$CONFIG_FILE" <(echo "$MCP_CONFIG") > "${CONFIG_FILE}.tmp"
    mv "${CONFIG_FILE}.tmp" "$CONFIG_FILE"
    echo "  MCP server registered in $CONFIG_FILE"
else
    # Fallback: check if already configured, otherwise warn
    if grep -q '"rlm"' "$CONFIG_FILE" 2>/dev/null; then
        echo "  MCP server already configured in $CONFIG_FILE"
    else
        echo ""
        echo "  Warning: jq not found. Please add the following to $CONFIG_FILE manually:"
        echo ""
        echo "  {"
        echo "    \"mcp\": {"
        echo "      \"rlm\": {"
        echo "        \"type\": \"local\","
        echo "        \"command\": [\"uv\", \"run\", \"--project\", \"$SCRIPT_DIR\", \"python\", \"mcp/server.py\"]"
        echo "      }"
        echo "    }"
        echo "  }"
        echo ""
    fi
fi

# --- Done ---
echo ""
echo "Done! RLM is now installed for OpenCode."
echo ""
echo "Features:"
echo "  - Context injection: previous session memories in system prompt"
echo "  - Auto-archival: sessions archived on compaction and idle"
echo "  - MCP tools: rlm_recall, rlm_remember, rlm_memory_list,"
echo "               rlm_memory_extract, rlm_forget"
echo ""
echo "To verify: start OpenCode and check 'opencode mcp list' for rlm"
