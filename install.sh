#!/usr/bin/env bash
# Install RLM: skill, hooks, and MCP server into Claude Code
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$HOME/.claude/skills/rlm"
HOOKS_DIR="$HOME/.claude/hooks"

echo "Installing RLM..."
echo ""

# ── 1. Skill prompt ────────────────────────────────────────────────────────────
echo "1/4 Installing /rlm skill..."
mkdir -p "$SKILL_DIR"
# Remove old symlink if present (old installs used ln -sf, which causes
# redirect to write through the symlink back into the source template)
rm -f "$SKILL_DIR/SKILL.md"
sed "s|__RLM_ROOT__|$SCRIPT_DIR|g" "$SCRIPT_DIR/skill/SKILL.md" > "$SKILL_DIR/SKILL.md"
echo "    → $SKILL_DIR/SKILL.md (paths substituted)"

# ── 2. Python package ──────────────────────────────────────────────────────────
echo "2/4 Installing Python package..."
cd "$SCRIPT_DIR"
uv sync
echo "    → uv sync complete"

# ── 3. Hooks (PreCompact, SessionEnd, SessionStart) ───────────────────────────
echo "3/4 Installing Claude Code hooks..."
mkdir -p "$HOOKS_DIR"

# Symlink hook scripts (semantic versions for improved tagging)
ln -sf "$SCRIPT_DIR/hooks/pre-compact-rlm-semantic.py"   "$HOOKS_DIR/rlm-precompact.py"
ln -sf "$SCRIPT_DIR/hooks/session-end-rlm-semantic.py"   "$HOOKS_DIR/rlm-sessionend.py"
ln -sf "$SCRIPT_DIR/hooks/session-start-rlm.py" "$HOOKS_DIR/rlm-sessionstart.py"
echo "    → $HOOKS_DIR/rlm-precompact.py (with semantic tagging)"
echo "    → $HOOKS_DIR/rlm-sessionend.py (with semantic tagging)"
echo "    → $HOOKS_DIR/rlm-sessionstart.py"

# Write hooks.json (merge if it already exists and has other hooks)
HOOKS_JSON="$HOOKS_DIR/hooks.json"
if [ -f "$HOOKS_JSON" ]; then
    echo "    → hooks.json already exists — please verify it includes RLM hooks"
    echo "      (see hooks/README.md for the required configuration)"
else
    cat > "$HOOKS_JSON" <<'EOF'
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$HOME/.claude/hooks/rlm-sessionstart.py\""
          }
        ],
        "description": "Inject recent project context from RLM memory"
      }
    ],
    "PreCompact": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$HOME/.claude/hooks/rlm-precompact.py\""
          }
        ],
        "description": "Archive conversation before compaction"
      }
    ],
    "SessionEnd": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$HOME/.claude/hooks/rlm-sessionend.py\""
          }
        ],
        "description": "Archive conversation on session end"
      }
    ]
  }
}
EOF
    echo "    → $HOOKS_JSON created"
fi

# ── 4. MCP server (user-scoped, available in all projects) ───────────────────
echo "4/4 Registering MCP server..."
CLAUDE_JSON="$HOME/.claude.json"
python3 -c "
import json, os, sys

path = '$CLAUDE_JSON'
try:
    with open(path, 'r') as f:
        data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    data = {}

servers = data.setdefault('mcpServers', {})
servers['rlm'] = {
    'type': 'stdio',
    'command': 'uv',
    'args': [
        'run',
        '--project', '$SCRIPT_DIR',
        'python', '$SCRIPT_DIR/mcp/server.py'
    ]
}

with open(path, 'w') as f:
    json.dump(data, f, indent=2)
print('    → Registered user-scoped MCP server in ' + path)
"
echo "    → On first use, Claude Code will ask you to approve the MCP server"

# Clean up old project-scoped .mcp.json if present
if [ -f "$SCRIPT_DIR/.mcp.json" ]; then
    rm "$SCRIPT_DIR/.mcp.json"
    echo "    → Removed old project-scoped .mcp.json"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "Done! RLM is installed."
echo ""
echo "Usage:"
echo "  /rlm \"find security issues\" ./src/        # Analyze content"
echo "  /rlm \"what do I know about auth?\"          # Recall from memory"
echo "  /rlm remember \"decision\" --tags \"arch\"     # Store to memory"
echo ""
echo "Auto-recall:"
echo "  SessionStart hook: injects recent project context at session start"
echo "  MCP tools (rlm_recall, rlm_remember, rlm_memory_list): available to"
echo "  the agent automatically — no /rlm invocation needed"
echo ""
echo "Hooks installed:"
echo "  SessionStart → inject context from memory"
echo "  PreCompact   → archive conversation before compaction"
echo "  SessionEnd   → archive conversation on session end"
echo ""
echo "Nothing was added to your project directory."
