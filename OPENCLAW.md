# RLM for OpenClaw

This branch adds OpenClaw compatibility to the Recursive Language Model (RLM) skill.

## What is RLM?

RLM gives AI agents two superpowers:

1. **📊 Analyze codebases beyond context limits** - Recursively analyze large codebases using sub-agent delegation
2. **🧠 Persistent memory across sessions** - Store and recall knowledge that survives restarts

## Installation

### Prerequisites

- OpenClaw installed (`brew install openclaw`)
- UV package manager (script will install if missing)

### Install the Skill

```bash
cd /opt/homebrew/lib/node_modules/openclaw/skills/
sudo mkdir -p rlm
sudo chown $USER rlm
cd rlm
git clone https://github.com/marknutter/recursive-ai.git rlm-src
cd rlm-src
git checkout openclaw-compatibility
./install-openclaw.sh
```

**Or manually:**

```bash
# Clone the repo
git clone https://github.com/marknutter/recursive-ai.git
cd recursive-ai
git checkout openclaw-compatibility

# Run install script
./install-openclaw.sh
```

The install script will:
1. Copy the skill file to OpenClaw's skills directory
2. Install Python dependencies via UV
3. Make the `rlm` CLI globally available

## Usage

### Mode 1: Code Analysis (Beyond Context Limits)

**Analyze large codebases:**

```
/rlm "find all security vulnerabilities" ./src
```

```
/rlm "summarize the architecture" ~/projects/myapp
```

```
/rlm "find uses of deprecated APIs" ./legacy-code
```

**How it works:**
1. You (orchestrator) scan metadata and chunk the codebase
2. Spawn sub-agents to analyze each chunk
3. Sub-agents extract and read actual content (keeps it out of your context)
4. You synthesize results without ever loading raw content

**Benefits:**
- Analyze millions of lines of code
- Stay under context limits
- Parallel processing via sub-agents
- Smart chunking strategies (by file, function, semantic units)

### Mode 2: Persistent Memory

**RLM includes MCP tools that are ALWAYS available:**

#### Store Knowledge

```javascript
// Tool call example (OpenClaw will expose these as functions)
rlm_remember({
  content: "Mark prefers Railway for cloud hosting. Uses it for Moxmo production.",
  tags: ["preferences", "infrastructure", "moxmo"],
  metadata: {
    source: "conversation-2026-02-19",
    importance: "medium"
  }
})
```

#### Recall Knowledge

```javascript
rlm_recall({
  query: "hosting preferences",
  limit: 5
})
// Returns: Top 5 relevant memories with similarity scores
```

#### Browse Memories

```javascript
rlm_memory_list({
  limit: 10,
  tags: ["moxmo"]
})
// Returns: 10 most recent entries tagged "moxmo"
```

#### Extract Specific Memories

```javascript
rlm_memory_extract({
  entry_ids: ["abc123", "def456"]
})
// Returns: Full content of those memory entries
```

#### Delete Memories

```javascript
rlm_forget({
  entry_ids: ["abc123"]
})
```

**When to use memory:**

✅ **Remember:**
- User preferences and patterns
- Project decisions and rationale
- Important facts that should persist
- Context that spans multiple sessions

✅ **Recall:**
- At session start (what do I know about this user?)
- Before recommendations (what are their preferences?)
- When context is missing (did we discuss this before?)

### Integration with Existing Memory

**RLM memory complements OpenClaw's existing memory system:**

- **MEMORY.md** → Narrative context, curated insights (use `memory_search` tool)
- **Daily logs** → Chronological session records  
- **RLM memory** → Structured, searchable, tagged knowledge

**Use both together:**
1. RLM memory for quick facts, preferences, structured data
2. MEMORY.md for narrative context, project history, relationships
3. Daily logs for chronological session records

## Architecture

**OpenClaw-specific changes:**

1. **Skill location:** `/opt/homebrew/lib/node_modules/openclaw/skills/rlm/`
2. **CLI access:** Global `rlm` command (via `uv tool install`)
3. **Sub-agent spawning:** Uses `sessions_spawn` instead of Claude Code's `Task` tool
4. **MCP tools:** Exposed via OpenClaw's tool system (not MCP servers)
5. **Metadata:** OpenClaw-compatible frontmatter with `requires` and `install` sections

## Differences from Claude Code Version

| Feature | Claude Code | OpenClaw |
|---------|-------------|----------|
| Skill location | `~/.claude/skills/rlm/` | `/opt/homebrew/lib/node_modules/openclaw/skills/rlm/` |
| CLI prefix | `cd <path> && uv run rlm` | Global `rlm` command |
| Sub-agents | `Task` tool | `sessions_spawn` tool |
| MCP tools | MCP server (`stdio://rlm`) | Native OpenClaw tools |
| Installation | `./install.sh` | `./install-openclaw.sh` |

## Development

**Test the skill:**

```bash
# In an OpenClaw session
/rlm "test query" ./test-directory
```

**Update the skill:**

```bash
cd /opt/homebrew/lib/node_modules/openclaw/skills/rlm/rlm-src
git pull
uv sync
```

**Uninstall:**

```bash
sudo rm -rf /opt/homebrew/lib/node_modules/openclaw/skills/rlm
uv tool uninstall rlm
```

## Contributing

This OpenClaw branch should stay in sync with the main Claude Code version. When updating:

1. Merge changes from `main` branch
2. Test that OpenClaw-specific adaptations still work
3. Update this README if behavior changes

## Support

- **RLM Issues:** https://github.com/marknutter/recursive-ai/issues
- **OpenClaw Issues:** https://github.com/openclaw/openclaw/issues
- **Documentation:** See [README.md](README.md) for detailed RLM algorithm docs

## License

Same as main RLM project (see LICENSE file).
