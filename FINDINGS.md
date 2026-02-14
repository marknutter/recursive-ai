# Findings: Is This a Logical Extrapolation of the RLM Paper?

## The Paper's Core Thesis

The RLM paper ([arxiv 2512.24601v2](https://arxiv.org/html/2512.24601v2)) demonstrates that LLMs can process inputs far beyond their context window by treating content as external data accessed through tools. The model never loads raw content into its context. Instead it:

1. **Scans** to produce metadata (file trees, sizes, structure outlines)
2. **Chunks** content into a manifest of IDs and previews
3. **Dispatches** sub-LLMs to extract and analyze individual chunks
4. **Iterates** if findings are insufficient — re-chunking, drilling down, expanding scope
5. **Synthesizes** subagent findings into a final answer

The key insight is architectural separation: the orchestrating LLM reasons about structure and makes decisions; subordinate LLMs handle raw content and return bounded findings. This lets the system scale to inputs 100x beyond the context window with no fine-tuning, no embeddings, and no RAG pipeline.

Five principles emerge from the paper:

- **Metadata-first**: The orchestrator sees summaries, never raw content
- **Bounded output**: Every tool interaction is capped (we use 4KB)
- **Subagent delegation**: Content inspection happens in disposable sub-contexts
- **Iterative refinement**: The loop can repeat with finer granularity or broader scope
- **Tool-mediated access**: All content flows through programmatic extraction, not direct reading

## What We Built Beyond the Paper

The paper applies RLM to code analysis — a single session analyzing a codebase, then discarding state. We extended it in four directions:

### 1. Persistent Memory (Knowledge Store)

**Extension**: Instead of analyzing a live codebase and throwing away the session, we store findings and external knowledge in a persistent `~/.rlm/memory/` directory and retrieve them later using the same scan-chunk-dispatch pattern.

**Relationship to paper**: This is a direct generalization. The paper says "give an LLM tools to inspect external data." A persistent file-based knowledge store *is* external data. The same metadata-first pattern works: the memory index (~200 bytes per entry) is the "scan" output, keyword search is the "chunk" selection, and subagent extraction is the content inspection. Nothing about the paper's architecture limits it to ephemeral analysis of code.

**What's new**: The paper assumes a known target path. Memory recall inverts this — the system must *find* what to inspect, not just *how* to inspect a given target. This required adding:
- A keyword-scored search index (the "which entries matter?" question the paper never asks)
- Tag-based filtering for domain narrowing
- Deep search that scans entry content, not just metadata

**Honest assessment**: This is a natural and arguably obvious generalization. Anyone reading the paper would ask "why not apply this to stored knowledge?" The contribution isn't the idea but the implementation — proving it works with zero external dependencies (no vector DB, no embeddings, no external search engine) on a real knowledge base of 337 entries spanning 15 years of chat history.

### 2. Grep Pre-Filtering

**Extension**: Before dispatching a subagent to evaluate a memory entry, we run a regex grep within the entry to confirm keyword presence. Entries that return "No matches" are skipped entirely.

**Relationship to paper**: The paper has an implicit version of this — the `extract --grep` command for search queries ("grep-first for search queries" is listed as a quick-path optimization). We promoted it from optional optimization to a mandatory step in the retrieval pipeline, applied systematically to every candidate entry before subagent dispatch.

**What's new**: The paper treats grep as a shortcut. We treat it as a gate. This changes the economics: in our San Diego recall test, deep search returned entries that matched on metadata but contained no relevant content. Without grep pre-filtering, 16 subagents were dispatched and 12 returned empty. With it, 2 subagents were dispatched and both returned substantive findings. Same quality, 8x fewer subagent calls.

**Honest assessment**: This is an engineering optimization, not a conceptual breakthrough. But it addresses a real scaling concern: as the memory store grows, false positives from keyword search increase, and each false positive wastes a subagent dispatch. Grep pre-filtering keeps the subagent count proportional to *relevant* entries rather than *matching* entries. At 337 entries this saves seconds; at 10,000 entries it could save minutes.

### 3. Graduated Dispatch

**Extension**: Instead of dispatching subagents for all matching entries at once, start with the top 4-5 highest-scoring entries. Evaluate whether the query is answered. Only dispatch more if gaps remain.

**Relationship to paper**: The paper's iteration loop (Step 5: "Evaluate — Are results sufficient? Need finer detail?") is conceptually similar, but it operates at the chunk level within a single analysis. Graduated dispatch applies the same principle at the entry level across the memory store: evaluate early results before committing more resources.

**What's new**: The paper dispatches all chunks in parallel and evaluates after. We dispatch in waves, using early results to decide whether later waves are needed. This is closer to how a human researcher works — read the most promising sources first, then decide if you need more.

**Honest assessment**: Another engineering optimization. The value scales with memory store size. At 5 matching entries it makes no difference. At 50 it prevents a 50-subagent pileup. The conceptual contribution is small — it's just "don't do everything at once" — but it significantly improves the user experience by reducing wait time for queries that have clear answers in the top results.

### 4. Self-Improving Retrieval Strategies

**Extension**: After each recall session, the system logs performance metrics (query, search terms, entries found vs. relevant, subagents dispatched) and assesses whether it discovered a reusable retrieval heuristic. If so, it writes the pattern to `~/.rlm/strategies/learned_patterns.md`. Future recall sessions load this file before starting, incorporating accumulated wisdom into their search strategy.

**Relationship to paper**: The paper has no analogue for this. The RLM algorithm is stateless across sessions — each analysis starts fresh with no memory of past analyses. Self-improving strategies add a feedback loop that the paper's architecture lacks entirely.

**What's new**: This is prompt-level online learning. The "model" being trained is the skill prompt's heuristics. The "training signal" is the agent's self-assessment of its own recall performance. The "weights" are natural language patterns in a markdown file. There's no gradient descent, no loss function, no training run — just an LLM reflecting on what worked and writing down reusable instructions for its future self.

Concrete example: After the first recall tests, the system learned patterns like:
- "Use vocabulary variants for topical queries" (because 'Iraq war' content might say 'Bush' or 'WMD' but not 'Iraq war')
- "Weekly chat archives need grep pre-filtering before dispatch" (because they match broadly but contain narrowly)
- "Longitudinal queries need temporal coverage" (check multiple time periods, not just the top-scoring one)

These patterns, once written, are loaded and applied by every future recall session without any human intervention.

**Honest assessment**: This is the most genuinely novel extension. It creates a system that gets better at retrieval through use — not by retraining embeddings or updating indices, but by accumulating natural language heuristics that an LLM can interpret and apply. The question is whether this scales: at 5 patterns it's clearly useful; at 50 patterns the file might become unwieldy; at 500 patterns it might start contradicting itself. The current design has no pruning, no conflict resolution, and no confidence scoring. But as a proof of concept for prompt-level online learning, it demonstrates something interesting: the LLM equivalent of "notes to self" that persist across sessions and measurably improve performance.

## How This Compares to RAG

The comparison to RAG is central to understanding whether this direction is viable.

### Where RLM Memory Outperforms RAG

**Semantic depth**: RAG retrieves document chunks based on vector similarity and presents them to the LLM in a single pass. RLM memory dispatches subagents that can *read, reason about, and evaluate* the retrieved content, then the orchestrator synthesizes across all evaluations. This is the difference between "here are some relevant passages" and "here's what an analyst found after reading each relevant document."

The Iraq War recall test illustrates this. RAG would return the 5 most similar chunks to "what did everyone think about the Iraq war." RLM memory found 8 people's opinions across 3 years of debate, reconstructed their positions including evolution over time, identified a 6:1 anti-war ratio, and captured the spectrum from moral philosophy to policy critique to conspiracy theory. This required reading multiple weekly archives, cross-referencing speakers across time periods, and synthesizing a political landscape — none of which single-pass retrieval can do.

**No embedding quality ceiling**: RAG's retrieval quality is bounded by its embedding model. If the embedding doesn't capture the nuance you need (e.g., that "WMD" is relevant to "Iraq war"), you won't retrieve the right chunks. RLM memory uses keyword search for candidate identification, then LLM evaluation for relevance assessment. The retrieval quality scales with the reasoning model's capability, not the embedding model's representation.

**Zero infrastructure**: No vector database, no embedding computation, no index rebuilding when the model changes. The entire system is files on disk accessed through Python's stdlib.

### Where RAG Outperforms RLM Memory

**Latency**: RAG returns results in milliseconds. RLM memory takes 30 seconds to several minutes depending on the number of entries to evaluate. This is the fundamental tradeoff: semantic depth vs. speed.

**Semantic matching**: Keyword search has real limitations. If someone stored a memory about "authentication bypass" and later queries "security vulnerabilities," keyword search might miss it entirely. Vector similarity would catch the semantic relationship. Our current mitigation (vocabulary variants, deep search) helps but doesn't fully solve this.

**Scale**: At 337 entries with JSON index files, everything is fast. At 100,000 entries, linear keyword scanning becomes untenable. RAG's vector indices are designed for efficient similarity search at scale. We would eventually need to add some form of indexing — though this could be as simple as SQLite FTS5 rather than a full vector database.

**Consistency**: RLM memory's quality depends on which model is orchestrating and how well the skill prompt guides it. Different model versions might interpret the same patterns file differently. RAG's retrieval is deterministic for a given query and index state.

### The Fundamental Difference

RAG answers the question: "What stored content is similar to this query?"

RLM memory answers the question: "What does an analyst conclude after investigating my stored knowledge about this topic?"

These serve different use cases. RAG is better for lookup tasks ("what's the API endpoint for user creation?"). RLM memory is better for synthesis tasks ("what's the overall security posture of this system based on everything I've found?"). The ideal system probably uses both — fast vector retrieval for candidate identification, then RLM-style subagent evaluation for deep analysis of the candidates.

## Is This a Logical Extrapolation?

### What follows directly from the paper

The paper establishes that LLMs can analyze arbitrary external data through metadata-first, bounded-output, subagent-delegated inspection. Applying this to a persistent knowledge store is a straightforward generalization — you're just changing "analyze this codebase" to "analyze this knowledge base." The architectural principles (metadata-first, bounded output, subagent delegation, iterative refinement) transfer without modification.

The memory system's search → grep → dispatch → synthesize pipeline is structurally identical to the paper's scan → chunk → dispatch → synthesize pipeline. The innovation is applying it to *retrieval* rather than *analysis*, which inverts the starting condition (you don't know where to look, vs. the paper where you know the target path) but preserves the processing pattern.

### What extends the paper into new territory

**Self-improving strategies** go beyond the paper in a meaningful way. The paper's algorithm is stateless — it doesn't learn from past sessions. Adding a feedback loop where the system accumulates retrieval heuristics and applies them in future sessions is a genuine architectural extension. It's not "the paper but bigger" — it's "the paper plus online learning at the prompt level." The paper gives you a capable analyst that forgets everything between sessions. Self-improving strategies give you an analyst that takes notes on its own techniques.

**Session continuity** — using the system to preserve its own conversational context — is a self-referential application the paper doesn't contemplate. The paper treats the LLM as a tool operator. We treat it as a persistent agent that can bootstrap its own memory across sessions. This is more a philosophical extension than a technical one, but it demonstrates that the RLM pattern is general enough to be self-hosting.

### What doesn't follow from the paper

**Keyword search as the retrieval backbone** is a pragmatic choice, not one the paper motivates. The paper assumes you know what you're analyzing (a given file path). We needed a way to find relevant entries in a growing store, and chose keyword scoring for simplicity. The paper's principles don't prescribe any particular search mechanism — they just require that the orchestrator sees bounded metadata, not raw content. A hybrid approach (vector retrieval for candidates, then RLM evaluation) might better serve the paper's philosophy of "use the best tool for each stage."

**The unified skill routing** (`/rlm` handling analysis, recall, and storage) is a UX decision orthogonal to the paper's contributions. It's convenient and reduces cognitive load, but it's not motivated by the paper's architecture.

## Scalability Concerns

The current system works well at 337 entries. Honest assessment of where it breaks:

**~1,000 entries**: Keyword search on the JSON index starts to slow. Deep search (scanning content) becomes noticeably slow. Mitigation: add a tag-based index for faster filtering.

**~10,000 entries**: Linear scanning is untenable. The index file itself becomes large. Mitigation: SQLite with FTS5 (full-text search) replaces the JSON index. Still zero external dependencies (sqlite3 is in Python's stdlib).

**~100,000 entries**: Subagent dispatch becomes the bottleneck — even with grep pre-filtering, the candidate set could be large. Mitigation: tiered search (coarse keyword → FTS5 → grep → subagent). The graduated dispatch pattern already handles this conceptually; it just needs faster candidate identification.

**The patterns file**: At 50+ learned patterns, the file might exceed what's useful in a prompt prefix. Mitigation: relevance-based pattern selection (only load patterns whose context matches the current query type).

None of these are fundamental blockers. They're engineering work that follows naturally from the architecture.

## What's Genuinely Novel

In order of novelty (most to least):

1. **Prompt-level online learning via self-improving strategies.** An LLM that writes retrieval heuristics for its future self, accumulating expertise in natural language. This is genuinely new territory — not fine-tuning, not RAG index updates, but an LLM training its own prompt through self-assessment.

2. **Two-tier retrieval as a RAG alternative.** Cheap keyword search for candidate identification + expensive LLM evaluation for relevance assessment. The quality scales with model capability rather than embedding quality. This isn't entirely new (some systems use LLM-based reranking), but applying it systematically with subagent delegation and iterative refinement is a distinct approach.

3. **Self-referential session continuity.** Using the knowledge retrieval system to preserve its own conversational context. This demonstrates the architecture's generality and creates a practical solution for LLM memory across sessions.

4. **Grep pre-filtering as a subagent gate.** Engineering optimization that changes retrieval economics by keeping subagent count proportional to relevant (not matching) entries.

5. **Zero-dependency persistent knowledge store.** Not novel in concept, but notable in execution — proving you can build effective long-term memory for an LLM with nothing but JSON files and Python's stdlib.

## Conclusion

The persistent memory system is a logical generalization of the RLM paper's architecture. The core principles — metadata-first access, bounded output, subagent delegation, iterative refinement — transfer cleanly from ephemeral code analysis to persistent knowledge retrieval. The grep pre-filtering and graduated dispatch are engineering optimizations that make the generalization practical.

The self-improving strategies extend the paper in a genuinely new direction. The paper gives you a powerful but stateless analysis tool. The strategies system makes it stateful — not by fine-tuning or retraining, but by having the LLM accumulate natural language heuristics about its own retrieval performance. Whether this constitutes a meaningful contribution to the field or just a clever hack depends on whether it scales beyond the current proof-of-concept stage. The early results are promising: 5 learned patterns measurably reduced subagent waste and improved search coverage across 4 diverse recall tests.

The honest answer to "is this a logical extrapolation?" is: mostly yes, with one piece that's genuinely novel. The memory system is the paper applied to a different domain. The self-improving strategies are something new.

## Next Steps

Looking back at what FINDINGS.md identified, there are three categories: quality gaps, scaling gaps, and the novel piece that could be pushed further.

**Biggest quality gap: semantic matching.** This is the most impactful problem. Keyword search can't find "authentication bypass" when you query "security vulnerabilities." Right now we mitigate with vocabulary variants in the skill prompt ("also try auth, login, password"), but that's the orchestrator guessing synonyms — it's brittle. Three options, escalating in complexity:

1. **LLM-generated search expansion** — Before running `rlm recall`, have the orchestrator generate 3-5 keyword variants of the query using its own knowledge. No new dependencies, just a smarter prompt step. Cheapest to implement.
2. **SQLite FTS5** — Replace the JSON index with SQLite full-text search. FTS5 has built-in ranking (BM25), handles stemming, and is still zero external dependencies (sqlite3 is in Python's stdlib). Solves both the semantic matching and the scale problem simultaneously.
3. **Hybrid retrieval** — Vector embeddings for candidate identification, then RLM subagent evaluation for deep analysis. Most powerful, but breaks the zero-dependency principle and adds API costs for embedding computation.

**Biggest scaling gap: the JSON index.** FINDINGS.md flagged this honestly — works at 337, gets slow around 1K, untenable at 10K. SQLite FTS5 fixes this and is a natural stepping stone. It also opens the door to more sophisticated queries (phrase matching, boolean operators, proximity search) without adding external dependencies.

**The novel piece worth pushing further: self-improving strategies.** At 5 patterns it works. The FINDINGS.md identified three missing pieces:

- **Confidence scoring** — Not all patterns are equally reliable. Some are validated across multiple sessions, others are one-off observations.
- **Relevance-based selection** — Don't load all patterns into every recall session. Match patterns to the query type.
- **Pruning** — Remove or merge patterns that contradict each other or become stale.

**Priority**: SQLite FTS5 first, because it solves two problems at once (semantic matching via BM25 ranking + scale) with zero new dependencies. Then strategy scaling to build on the most novel aspect. The LLM-generated search expansion could be done quickly as a skill prompt change in parallel with either.
