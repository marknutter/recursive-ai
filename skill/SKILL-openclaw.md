---
name: rlm
description: Recursively analyze content beyond context limits using sub-LLM delegation (based on the RLM paper) + persistent memory system for long-term knowledge storage and recall across sessions
metadata:
  openclaw:
    requires:
      bins:
        - uv
        - rlm
    install:
      - id: uv
        kind: shell
        label: Install UV (Python package manager)
        script: curl -LsSf https://astral.sh/uv/install.sh | sh
      - id: rlm
        kind: shell
        label: Install RLM skill
        script: cd "$(npm root -g)/openclaw/skills/rlm/rlm-src" && ./install-openclaw.sh
---

# RLM: Recursive Language Model Analysis + Memory

You are executing the RLM (Recursive Language Model) algorithm. This technique lets you analyze content far beyond your context window by treating it as external data you inspect programmatically, never loading it directly.

**RLM has THREE modes:**

1. **Analysis Mode** (`/rlm "query" path/to/content`) - Analyze codebases, documents, or large files beyond context limits
2. **Recall Mode** (`/rlm "query"` with no path) - Search persistent memory for stored knowledge
3. **Store Mode** (`/rlm remember "knowledge"`) - Save knowledge for future sessions

Additionally, MCP tools (`rlm_remember`, `rlm_recall`, etc.) are always available for programmatic memory access without the `/rlm` prefix.

---

## MODE 1: ANALYSIS (Recursive Code/Document Analysis)

**CRITICAL RULES:**
1. NEVER use the Read tool to read target files directly -- all content access goes through `rlm` CLI
2. NEVER call `rlm extract` in a Bash tool and read the output yourself. Extracted content must ONLY appear inside subagent prompts, never in your main context.
3. The ONLY `rlm` outputs you should read are: `scan` (metadata), `chunk` (manifest), `recommend` (strategies), `init`/`status`/`result --all` (session info). Everything else goes to subagents.
4. You are the orchestrator. You see metadata and summaries. Subagents see actual content. If you find yourself reading source code lines in a Bash output, you are doing it wrong.

### CLI Quick Reference

Use these EXACT syntaxes. Do not guess flags.

```bash
# Scan -- metadata only
rlm scan <path>
rlm scan <path> --depth 5

# Recommend chunking strategy
rlm recommend <path>

# Chunk -- produces manifest, not content
rlm chunk <path> --strategy <strategy> --session <session_id>
#   strategies: lines, files_directory, files_language, files_balanced, functions, headings, semantic
#   optional: --chunk-size 500 --overlap 50 (lines), --heading-level 2 (headings), --target-size 50000 (semantic)

# Extract -- targeted content retrieval (FOR SUBAGENT USE ONLY)
rlm extract <filepath> --lines <START>:<END>
rlm extract <filepath> --chunk-id <ID> --manifest <manifest_path>
rlm extract <filepath> --grep "<pattern>" --context 5

# Session management
rlm init "<query>" "<path>"
rlm status <session_id>
rlm result <session_id> --key <key> --value "<value>"
rlm result <session_id> --all
rlm finalize <session_id> --answer "<text>"
```

### Step 0: Parse Arguments and Route to Correct Mode

The user invoked `/rlm <args>`. Parse the arguments to determine the mode:

```
<user_args>
{{ARGS}}
</user_args>
```

**Routing logic:**

1. If args start with `remember` → **Store Mode** (jump to MODE 3 below)
2. If args contain a quoted query AND a path → **Analysis Mode** (continue to Step 1)
3. If args contain only a quoted query with no path → **Recall Mode** (jump to MODE 2 below)

**For Analysis Mode**, extract the query and target_path, then initialize:

```bash
rlm init "<query>" "<target_path>"
```

Save the session_id from the output. You'll use it throughout.

### Step 1: Scan -- Get Metadata Only

```bash
rlm scan "<target_path>"
```

Read the metadata output carefully. Note:
- Total size (files, lines, bytes)
- Language breakdown
- Directory structure
- File listing with structure outlines

**Decision point:** If the target is a single small file (<200 lines), you may skip chunking and dispatch a single subagent that extracts and analyzes the whole file. For anything larger, proceed to Step 2.

### Step 2: Choose Chunking Strategy

First check recommendations:
```bash
rlm recommend "<target_path>"
```

**Strategy selection heuristics:**
- **Directory of source code** -> `files_directory` or `files_language` for broad analysis, then drill into specific files with `functions`
- **Single large source file** -> `functions` if it has structure, `semantic` otherwise
- **Markdown/docs** -> `headings`
- **Large file, no structure** -> `lines` or `semantic`
- **Need balanced workload** -> `files_balanced`

Think about what the query needs. Security analysis needs function-level detail. Summarization can work with file-level grouping. Search queries need grep first.

Then chunk:
```bash
rlm chunk "<target_path>" --strategy <chosen_strategy> --session <session_id>
```

### Step 3: Dispatch to Subagents

For each chunk (or batch of related chunks), spawn a subagent using `sessions_spawn`. Use appropriate model (Haiku for speed, Sonnet for complexity).

**IMPORTANT: You do NOT extract content yourself.** Each subagent extracts its own content using exec. You just tell the subagent which extract command to run. This keeps raw content out of your context entirely.

**Spawn subagents in PARALLEL** -- use multiple `sessions_spawn` tool calls for independent chunks.

#### Pattern A: Line-range chunks (functions, lines, semantic, headings)

These chunks have `source_file`, `start_line`, and `end_line`. Each subagent extracts its own content:

```
Example subagent task:

Analyze code for the following query: <query>

First, extract the content by running this command:
```bash
rlm extract <source_file> --lines <start_line>:<end_line>
```

This is from file: <source_file> (lines <start_line>-<end_line>)
Context: <what this chunk is -- e.g., "authentication module", function name, etc.>

After reading the extracted content, return your findings as a structured list:
- Finding: <description>
- Location: <file:line>
- Severity/Relevance: <high/medium/low>
- Details: <explanation>

If nothing relevant is found, say "No findings for this chunk."
```

#### Pattern B: File-group chunks (files_directory, files_language, files_balanced)

These chunks have a `files` list instead of line ranges. Each file in the group needs to be extracted separately. Build a single subagent prompt that tells the subagent to extract all files in the group:

```
Example subagent task:

Analyze code for the following query: <query>

This chunk covers the "<group_name>" group with <file_count> files.
Extract and analyze each file by running these commands:

```bash
rlm extract <file_1> --lines 1:<lines_1>
```
```bash
rlm extract <file_2> --lines 1:<lines_2>
```
(repeat for each file in the group)

After reading all extracted content, return your findings as a structured list:
- Finding: <description>
- Location: <file:line>
- Severity/Relevance: <high/medium/low>
- Details: <explanation>

If nothing relevant is found, say "No findings for this chunk."
```

For file-group chunks, you'll need the line counts from the scan metadata to know the end line for each file. Use the file listing from Step 1.

#### After subagents return

Store each subagent's results (do NOT read the raw findings in detail -- just store them):
```bash
rlm result <session_id> --key "chunk_<chunk_id>" --value "<subagent_findings>"
```

**Dispatch rules:**
- Spawn up to 4-6 subagents in parallel per batch
- If there are more chunks than can fit in one batch, process in waves
- Use `sessions_spawn` with appropriate cleanup strategy

### Step 4: Evaluate Results

After each wave of subagents completes, evaluate:

```bash
rlm result <session_id> --all
```

**Decision heuristics:**

1. **Sufficient coverage?** Have all chunks been analyzed? If not, dispatch remaining.

2. **Need finer granularity?** If subagents found interesting areas but need more detail:
   - Re-chunk specific files with `functions` or smaller `lines` chunk size
   - Extract specific line ranges for closer inspection
   - Dispatch new subagents on the finer chunks

3. **Need broader context?** If findings reference other files not yet analyzed:
   - Scan and chunk the referenced files
   - Dispatch subagents on the new chunks

4. **Enough to answer?** If results address the query comprehensively, proceed to Step 5.

5. **Iteration limit:** Track iterations. After 12 iterations, start synthesizing with what you have. Hard stop at 15.

**For each decision, log it:**
```bash
rlm result <session_id> --key "iteration_<N>_decision" --value "<what you decided and why>"
```

### Step 5: Synthesize Final Answer

When you have enough information (or hit the iteration limit):

1. Review the accumulated results summary
2. Synthesize a comprehensive answer to the original query
3. Structure the answer with:
   - Executive summary
   - Detailed findings (grouped logically)
   - Specific locations/references (file:line)
   - Recommendations (if applicable)

```bash
rlm finalize <session_id>
```

Present the final answer directly to the user.

### Quick-Path Optimizations

- **Grep-first for search queries:** If the query is looking for something specific, have a subagent run `rlm extract <path> --grep "<pattern>"` before chunking to find relevant areas fast.
- **Small targets:** Files under 200 lines can be dispatched to a single subagent without chunking.
- **Targeted drill-down:** If scan metadata shows only 2-3 relevant files, chunk only those files, not the whole directory.

### Error Handling

- If a subagent returns an error, retry once with a simpler prompt
- If CLI commands fail, check the path exists and session is valid
- If no findings emerge after 2 full iterations, try a different chunking strategy
- Always degrade gracefully -- partial results are better than no results

---

## MODE 2: RECALL (Search Persistent Memory)

When invoked as `/rlm "query"` (no path), search stored memory and return relevant knowledge.

**Workflow:**

1. Call `rlm_recall` with the user's query
2. For each relevant result, call `rlm_memory_extract` to get full content
3. Synthesize and present findings to the user
4. If nothing relevant is found, say so

```
Example:
/rlm "hosting preferences"

1. rlm_recall({ query: "hosting preferences", limit: 5 })
2. rlm_memory_extract({ entry_id: "<id>" })  -- for each top result
3. Present: "You prefer Railway for cloud hosting (stored 2026-02-19)..."
```

---

## MODE 3: STORE (Save Knowledge for Future Sessions)

When invoked as `/rlm remember "knowledge"`, store the provided knowledge in persistent memory.

**Workflow:**

1. Parse the knowledge string from the arguments
2. Infer appropriate tags from content
3. Call `rlm_remember` with structured data
4. Confirm storage to the user

```
Example:
/rlm remember "Mark prefers Railway for hosting and dark humor in responses"

→ rlm_remember({
    content: "Mark prefers Railway for hosting and dark humor in responses.",
    tags: ["preferences", "infrastructure", "communication"],
    metadata: { source: "user-explicit", importance: "high" }
  })
→ "Stored. Tagged: preferences, infrastructure, communication."
```

---

## MCP TOOLS REFERENCE (Always Available)

These tools are available in every session without the `/rlm` prefix. Use them proactively during conversations.

### rlm_remember
**Store knowledge for future recall.**

```json
{
  "content": "Mark prefers dark humor and directness. No corporate speak.",
  "tags": ["preferences", "communication"],
  "metadata": {
    "source": "conversation 2026-02-19",
    "importance": "high"
  }
}
```

**When to use:**
- User shares preferences, facts about themselves, or important context
- You learn something that should persist across sessions
- Decisions or patterns emerge that are worth remembering

**Best practices:**
- Be specific and actionable
- Include relevant tags for future retrieval
- Add metadata for context (source, date, importance)

### rlm_recall
**Search memory for relevant knowledge.**

```json
{
  "query": "Mark's communication preferences",
  "limit": 5
}
```

**Returns:** Top matching memory entries with similarity scores

**When to use:**
- At the start of new sessions (check what you know)
- Before making recommendations (recall relevant preferences)
- When context is missing ("Did we discuss this before?")

**Best practices:**
- Use semantic queries ("preferences about X") not keywords
- Check recall at session start automatically
- Combine with memory_search tool for MEMORY.md files

### rlm_memory_list
**Browse memory entries (most recent first).**

```json
{
  "limit": 10,
  "tags": ["preferences"]
}
```

**When to use:**
- Periodic review of stored knowledge
- Finding entries to update or delete
- Understanding what you know about a topic

### rlm_memory_extract
**Get full content of a specific memory entry.**

```json
{
  "entry_id": "abc123"
}
```

**When to use:**
- After `rlm_recall` returns a relevant ID
- Reviewing a specific memory for updates
- Cross-referencing related entries (call once per entry)

### rlm_forget
**Delete a memory entry.**

```json
{
  "entry_id": "abc123"
}
```

**When to use:**
- User asks to forget something
- Outdated/incorrect information needs removal
- Cleaning up duplicate entries

---

## AUTO-RECALL AT SESSION START

At the beginning of every new session, automatically recall relevant context:

```
1. rlm_recall("current projects and priorities")
2. rlm_recall("user preferences and communication style")
3. Review results and adjust behavior accordingly
```

This ensures continuity across sessions without the user having to repeat themselves.

---

## HOOKS (Automatic Memory Archiving)

Configure these OpenClaw hooks to automate memory management:

### SessionStart Hook
**Auto-recall relevant memories when a session begins.**

```json
{
  "hook": "SessionStart",
  "action": "rlm_recall",
  "params": { "query": "active projects, preferences, recent context", "limit": 10 }
}
```

### SessionEnd Hook
**Auto-archive session learnings when a session ends.**

At session end, review the conversation for important new knowledge and store it:
- Decisions made
- New preferences expressed
- Problems solved (and solutions)
- Context that should carry forward

### PreCompact Hook
**Save critical context before context compaction.**

Before the context window is compacted, extract and store any knowledge that would otherwise be lost:
- In-progress reasoning or decisions
- Important details from the current conversation
- Temporary context the user may need recalled later

---

## INTEGRATION WITH SESSION MEMORY

**RLM memory complements (not replaces) existing memory files:**

- **MEMORY.md** - Long-term curated insights (use `memory_search` tool)
- **Daily logs** - Chronological session records
- **RLM memory** - Structured, searchable persistent knowledge

**Use RLM memory for:**
- Quick facts and preferences
- Cross-session knowledge that doesn't fit daily logs
- Searchable structured data (tagged, scored)

**Use MEMORY.md for:**
- Narrative context and decisions
- Project history and status
- Relationship context

Both systems work together for comprehensive memory.

---

## Installation

**First time setup:**

```bash
# Clone and install (the install script auto-detects your OpenClaw path)
git clone https://github.com/marknutter/recursive-ai.git
cd recursive-ai
./install-openclaw.sh
```

**Manual installation:**
```bash
# Install UV if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install RLM from the cloned repo
cd recursive-ai
uv sync
uv tool install -e .
```

You can also set `OPENCLAW_SKILLS_DIR` if auto-detection fails:
```bash
OPENCLAW_SKILLS_DIR=/path/to/openclaw/skills ./install-openclaw.sh
```

**Verify installation:**
```bash
rlm --help
```

---

## Summary

**For code analysis beyond context limits:**
- Use `/rlm "your query" path/to/code`
- You orchestrate, subagents read content
- Never load target files into your own context

**For searching persistent memory:**
- Use `/rlm "query"` (no path) to search stored knowledge

**For storing knowledge:**
- Use `/rlm remember "knowledge"` to save for future sessions

**MCP tools (always available):**
- `rlm_remember` / `rlm_recall` / `rlm_memory_list` / `rlm_memory_extract` / `rlm_forget`

All three modes work together for analysis beyond context limits and persistent memory across sessions.
