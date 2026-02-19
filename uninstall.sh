#!/usr/bin/env bash
# Uninstall RLM: remove skill, hooks, and MCP server from Claude Code
set -euo pipefail

SKILL_DIR="$HOME/.claude/skills/rlm"
HOOKS_DIR="$HOME/.claude/hooks"
CLAUDE_JSON="$HOME/.claude.json"

echo "Uninstalling RLM..."
echo ""

# ── 1. Skill prompt ────────────────────────────────────────────────────────────
if [ -d "$SKILL_DIR" ]; then
    rm -rf "$SKILL_DIR"
    echo "1/4 Removed skill directory: $SKILL_DIR"
else
    echo "1/4 Skill directory not found (already removed)"
fi

# ── 2. Hooks ───────────────────────────────────────────────────────────────────
removed_hooks=0
for hook in rlm-precompact.py rlm-sessionend.py rlm-sessionstart.py; do
    if [ -f "$HOOKS_DIR/$hook" ] || [ -L "$HOOKS_DIR/$hook" ]; then
        rm -f "$HOOKS_DIR/$hook"
        removed_hooks=$((removed_hooks + 1))
    fi
done
echo "2/4 Removed $removed_hooks hook symlink(s) from $HOOKS_DIR"

# Remove RLM entries from hooks.json if it exists
HOOKS_JSON="$HOOKS_DIR/hooks.json"
if [ -f "$HOOKS_JSON" ]; then
    python3 -c "
import json, sys

with open('$HOOKS_JSON', 'r') as f:
    data = json.load(f)

hooks = data.get('hooks', {})
changed = False

for event in ['SessionStart', 'PreCompact', 'SessionEnd']:
    if event in hooks:
        original = hooks[event]
        filtered = [
            m for m in original
            if not any('rlm-' in h.get('command', '') for h in m.get('hooks', []))
        ]
        if len(filtered) != len(original):
            changed = True
            if filtered:
                hooks[event] = filtered
            else:
                del hooks[event]

if changed:
    if hooks:
        data['hooks'] = hooks
    else:
        del data['hooks']
    with open('$HOOKS_JSON', 'w') as f:
        json.dump(data, f, indent=2)
    print('    → Removed RLM entries from hooks.json')
else:
    print('    → No RLM entries found in hooks.json')
" 2>/dev/null || echo "    → Could not parse hooks.json — please check manually"
fi

# Also clean RLM hooks from ~/.claude/settings.json if present
SETTINGS_JSON="$HOME/.claude/settings.json"
if [ -f "$SETTINGS_JSON" ]; then
    python3 -c "
import json

with open('$SETTINGS_JSON', 'r') as f:
    data = json.load(f)

hooks = data.get('hooks', {})
changed = False

for event in list(hooks.keys()):
    original = hooks[event]
    filtered = [
        m for m in original
        if not any('rlm' in h.get('command', '').lower() for h in m.get('hooks', []))
    ]
    if len(filtered) != len(original):
        changed = True
        if filtered:
            hooks[event] = filtered
        else:
            del hooks[event]

if changed:
    with open('$SETTINGS_JSON', 'w') as f:
        json.dump(data, f, indent=2)
    print('    → Removed RLM entries from settings.json')
" 2>/dev/null || true
fi

# ── 3. MCP server ─────────────────────────────────────────────────────────────
if [ -f "$CLAUDE_JSON" ]; then
    python3 -c "
import json

with open('$CLAUDE_JSON', 'r') as f:
    data = json.load(f)

servers = data.get('mcpServers', {})
if 'rlm' in servers:
    del servers['rlm']
    if not servers:
        del data['mcpServers']
    with open('$CLAUDE_JSON', 'w') as f:
        json.dump(data, f, indent=2)
    print('3/4 Removed MCP server from $CLAUDE_JSON')
else:
    print('3/4 No RLM MCP server found in $CLAUDE_JSON')
" 2>/dev/null || echo "3/4 Could not parse $CLAUDE_JSON — please check manually"
else
    echo "3/4 No $CLAUDE_JSON found"
fi

# ── 4. Global CLI tool ────────────────────────────────────────────────────────
if command -v uv &>/dev/null && uv tool list 2>/dev/null | grep -q "^rlm "; then
    uv tool uninstall rlm
    echo "4/4 Removed global CLI tool (rlm, rlm-tui)"
else
    echo "4/4 No global CLI tool installed (or uv not available)"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "RLM has been uninstalled from Claude Code."
echo ""
echo "Your memory data is preserved at ~/.rlm/ — delete it manually if you"
echo "want to remove all stored memories:"
echo ""
echo "  rm -rf ~/.rlm"
echo ""
echo "The cloned repo can also be deleted:"
echo ""
echo "  rm -rf $(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo ""
