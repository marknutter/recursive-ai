# RLM Episodic Memory Hooks

This directory contains Claude Code hooks for automatic episodic memory archiving.

## Installation

Add **both hooks** to your `~/.claude/hooks/hooks.json` file for complete coverage:

```json
{
  "hooks": {
    "PreCompact": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"/ABSOLUTE/PATH/TO/recursive-ai/hooks/pre-compact-rlm.py\""
          }
        ],
        "description": "Archive conversation before compaction (manual or auto)"
      }
    ],
    "SessionEnd": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"/ABSOLUTE/PATH/TO/recursive-ai/hooks/session-end-rlm.py\""
          }
        ],
        "description": "Archive conversation on session end (catches non-compacted sessions)"
      }
    ]
  }
}
```

**Replace `/ABSOLUTE/PATH/TO/recursive-ai` with your actual project path.**

### Alternative: Symlink Installation

```bash
# Create global hooks directory if needed
mkdir -p ~/.claude/hooks

# Symlink both RLM hooks
ln -s "$(pwd)/hooks/pre-compact-rlm.py" ~/.claude/hooks/rlm-precompact.py
ln -s "$(pwd)/hooks/session-end-rlm.py" ~/.claude/hooks/rlm-sessionend.py
```

Then reference in `~/.claude/hooks/hooks.json`:

```json
{
  "hooks": {
    "PreCompact": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$HOME/.claude/hooks/rlm-precompact.py\""
          }
        ],
        "description": "Archive before compaction"
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
        "description": "Archive on session end"
      }
    ]
  }
}
```

## What It Does

### PreCompact Hook (pre-compact-rlm.py)
Fires **before every compaction** (manual or automatic):
1. Exports full conversation transcript
2. Stores in `~/.rlm/memory/` using SQLite + FTS5
3. Tags with: `conversation`, `session`, project name, date
4. Marks session as archived (prevents duplicate archiving)

### SessionEnd Hook (session-end-rlm.py)
Fires **when session ends without compaction**:
1. Checks if session was already archived (within last 60 seconds)
2. If not, exports and stores the conversation
3. Ensures zero data loss even if user quits without compacting

**Together, these hooks guarantee 100% conversation capture.**

## Benefits

- **Survive compaction**: Important context is never lost
- **Cross-session continuity**: Pick up where you left off days/weeks later
- **Long-term memory**: Build a searchable knowledge base of all your work
- **RLM-powered recall**: Use chunking to efficiently retrieve from large conversation archives
- **Complete coverage**: Both manual compaction and session end events captured

## Testing

After installing, test both hooks:

### Test PreCompact Hook
```bash
# In Claude Code, manually run: /compact
# Check hook output in console
```

### Test SessionEnd Hook
```bash
# Start a conversation, then quit Claude Code
# Check hook output in console
```

### Verify Archives

**Primary Interface (in Claude Code):**
```
# Search archived conversations
/rlm "topic you discussed"

# Search with specific tags
/rlm "topic" --tags conversation,project-name
```

**CLI Interface (for debugging/scripting):**
```bash
# List all conversation memories
uv run rlm memory-list --tags conversation

# Search for specific topics
uv run rlm recall "topic you discussed" --tags conversation

# View a specific memory
uv run rlm memory-extract <memory-id>
```

## Troubleshooting

If archiving fails:
- Ensure `uv` is installed: `uv --version`
- Ensure RLM is set up: `uv run rlm --help`
- Check logs: archiving failures don't block compaction/session end
- Hook logs appear in Claude Code's console output
- Check marker files: `~/.claude/sessions/*.rlm-archived`

## Deduplication

The hooks use marker files to prevent duplicate archiving:
- PreCompact creates `.rlm-archived` marker file
- SessionEnd checks for recent marker (<60 seconds old)
- If marker exists and is recent, SessionEnd skips archiving
- This prevents the same conversation from being stored twice
