# RLM Episodic Memory Hooks

This directory contains Claude Code hooks for automatic episodic memory archiving.

## Installation

Add this to your `~/.claude/hooks/hooks.json` file:

```json
{
  "hooks": {
    "PreCompact": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "node \"/ABSOLUTE/PATH/TO/recursive-ai/hooks/pre-compact-rlm.js\""
          }
        ],
        "description": "Archive conversation to RLM episodic memory before compaction"
      }
    ]
  }
}
```

**Replace `/ABSOLUTE/PATH/TO/recursive-ai` with your actual project path.**

Alternatively, symlink the hook to your global hooks directory:

```bash
# Create global hooks directory if needed
mkdir -p ~/.claude/hooks

# Symlink the RLM hook
ln -s "$(pwd)/hooks/pre-compact-rlm.js" ~/.claude/hooks/rlm-archive.js
```

Then reference it in `~/.claude/hooks/hooks.json`:

```json
{
  "hooks": {
    "PreCompact": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "node \"$HOME/.claude/hooks/rlm-archive.js\""
          }
        ],
        "description": "Archive conversation to RLM episodic memory before compaction"
      }
    ]
  }
}
```

## What It Does

Before context compaction, this hook:

1. **Exports** the full conversation transcript using `examples/export_session.py`
2. **Stores** it in `~/.rlm/memory/` using SQLite + FTS5
3. **Tags** with: `conversation`, `session`, project name, date
4. **Enables** cross-session recall via `/rlm "what did we discuss about X?"`

## Benefits

- **Survive compaction**: Important context is never lost
- **Cross-session continuity**: Pick up where you left off days/weeks later
- **Long-term memory**: Build a searchable knowledge base of all your work
- **RLM-powered recall**: Use chunking to efficiently retrieve from large conversation archives

## Testing

After installing, trigger a manual compaction in Claude Code, then check:

```bash
# List all conversation memories
uv run rlm list --tags conversation

# Search for specific topics
uv run rlm recall "topic you discussed" --tags conversation

# View a specific memory
uv run rlm get <memory-id>
```

## Troubleshooting

If archiving fails:
- Ensure `uv` is installed: `uv --version`
- Ensure RLM is set up: `uv run rlm --help`
- Check logs: compaction will proceed even if archiving fails
- Hook logs appear in Claude Code's console output
