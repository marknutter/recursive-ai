# Issue: Parametric personality layer via LoRA fine-tuning

**Title:** feat: Explore parametric personality layer — LoRA fine-tuning for implicit knowledge capture

**Priority:** Future exploration (Phase 5) — depends on structured fact extraction being implemented first

## Summary

RLM's memory is entirely **non-parametric** — everything is stored as text in SQLite and retrieved via FTS5 search. This works well for discrete facts and episode recall, but misses a class of knowledge that's hard to capture as database rows: implicit working patterns, communication style preferences, domain expertise contours, and behavioral tendencies that emerge across hundreds of sessions.

This issue proposes a **parametric personality layer**: a LoRA-fine-tuned local model (Llama 3.1 8B) trained on archived conversations that captures these implicit patterns and periodically distills them into artifacts the existing RLM pipeline can consume.

## Core Insight

LLMs are excellent at encoding patterns from training data — that's why they "know" who Genghis Khan was. The same mechanism could encode "who this user is to work with" if fine-tuned on their conversation history. The key is scoping it correctly:

- **NOT for discrete fact recall** — structured storage (SQLite FTS5) is strictly better for that (100% precision, inspectable, updatable)
- **FOR pattern encoding** — preferences, working style, domain fluency, implicit knowledge that's hard to articulate as explicit facts

## Architecture: Offline Distillation Oracle

The personality model is **not** a live oracle running alongside Claude during sessions. It's a batch process that periodically distills implicit knowledge into text artifacts consumed by existing pipelines. This avoids requiring GPU during sessions and integrates with zero changes to the runtime architecture.

```
                         MONTHLY PIPELINE
                         ═══════════════

  ~/.rlm/memory/memory.db          Archived Transcripts
  (337+ sessions)                  (~50-80KB each, 35-40% signal)
          │                                  │
          ▼                                  ▼
  ┌──────────────────────────────────────────────┐
  │  Step 1: SYNTHETIC Q&A GENERATION            │
  │  (Claude API, batch mode)                    │
  │                                              │
  │  Input: 20-30 recent transcripts             │
  │  Output: ~500-1000 Q&A pairs like:           │
  │    Q: "How does the user handle testing?"    │
  │    A: "Prefers pytest, writes tests after    │
  │        implementation, focuses on..."         │
  └──────────────────┬───────────────────────────┘
                     │
                     ▼
  ┌──────────────────────────────────────────────┐
  │  Step 2: LoRA FINE-TUNE                      │
  │  (Llama 3.1 8B + QLoRA via Unsloth)         │
  │                                              │
  │  ~30-60 min on consumer GPU (RTX 3090/4090)  │
  │  Output: ~/.rlm/personality/adapter/         │
  │          (~50-200MB LoRA weights)             │
  └──────────────────┬───────────────────────────┘
                     │
                     ▼
  ┌──────────────────────────────────────────────┐
  │  Step 3: KNOWLEDGE EXTRACTION                │
  │  (Query fine-tuned model, batch)             │
  │                                              │
  │  Run ~50-100 structured queries:             │
  │  "What are user's Python preferences?"       │
  │  "How does user approach debugging?"         │
  │  "What architectural patterns recur?"        │
  │                                              │
  │  Output:                                     │
  │  ├─ USER_PROFILE.md  (SessionStart inject)   │
  │  ├─ Structured facts → facts table           │
  │  └─ Pattern entries → entries table           │
  └──────────────────────────────────────────────┘
```

### Why offline distillation, not a live oracle

| | Live Oracle | Offline Distillation |
|---|---|---|
| **GPU during sessions** | Required (8B model = ~6GB VRAM) | Not needed |
| **Latency** | Adds 2-5s per query | Zero (artifacts are pre-generated text) |
| **Integration complexity** | New MCP tool, routing logic, model server | Feeds into existing pipeline (entries + SessionStart) |
| **Failure mode** | Model server crashes = degraded recall | Stale profile = slightly outdated preferences |
| **User hardware** | Needs GPU for every session | Needs GPU once a month (or use cloud) |

The offline approach captures ~80% of the value with ~20% of the complexity.

## Detailed Engineering Design

### Step 1: Training Data Pipeline (`rlm/personality/dataset.py`, ~800-1000 lines)

This is the hardest and most critical component. Raw transcripts are noisy — they need to be transformed into Q&A pairs that teach the model *about* the user, not to parrot conversations.

**Pipeline:**

```python
def build_training_dataset(db_path, output_path, max_sessions=30):
    """Generate synthetic Q&A pairs from archived transcripts."""

    # 1. Pull recent session transcripts (full-transcript tagged entries)
    transcripts = db.search_by_tags(["full-transcript"], limit=max_sessions)

    # 2. For each transcript, generate Q&A pairs via Claude API (batch)
    #    Using Anthropic's Message Batches API for cost efficiency
    #    (~$0.30/transcript at Haiku pricing for 60KB input)
    pairs = []
    for transcript in transcripts:
        batch_result = generate_qa_pairs(transcript.content)
        pairs.extend(batch_result)

    # 3. Deduplicate and quality-filter
    pairs = deduplicate_by_similarity(pairs)
    pairs = filter_low_quality(pairs)

    # 4. Format for fine-tuning (Alpaca/ChatML format)
    write_jsonl(output_path, format_for_training(pairs))
```

**The Q&A generation prompt** (sent to Claude for each transcript):

```
Given this conversation transcript between a user and an AI assistant,
generate 15-30 question-answer pairs that capture IMPLICIT knowledge
about the user. Focus on:

1. Technical preferences (languages, frameworks, tools, patterns)
2. Working style (how they debug, plan, review, communicate)
3. Project context (what they're building, what matters to them)
4. Decision patterns (what tradeoffs they favor)
5. Communication preferences (verbosity, formality, detail level)

Format each as:
Q: [question someone might ask about this user]
A: [answer based on evidence in the transcript]

Do NOT generate pairs about:
- One-time facts with no pattern significance
- Tool outputs or code content
- Generic programming knowledge
```

**Cost per run:** 30 transcripts x ~60KB = ~1.8MB input. Using Haiku batch API: **~$0.50/month**.

### Step 2: Fine-Tuning Orchestration (`rlm/personality/train.py`, ~400 lines)

```python
def train_personality_adapter(
    dataset_path: str,
    base_model: str = "unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit",
    output_dir: str = "~/.rlm/personality/adapter",
    epochs: int = 3,
    lora_rank: int = 16,
    lora_alpha: int = 32,
):
    """Fine-tune LoRA adapter on personality Q&A pairs."""

    from unsloth import FastLanguageModel

    # Load 4-bit quantized base model
    model, tokenizer = FastLanguageModel.from_pretrained(
        base_model, load_in_4bit=True
    )

    # Apply LoRA to attention layers
    model = FastLanguageModel.get_peft_model(
        model, r=lora_rank, lora_alpha=lora_alpha,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    )

    # Train (~500-1000 pairs, 3 epochs, ~30 min on RTX 3090)
    trainer = SFTTrainer(
        model=model, dataset=load_dataset(dataset_path),
        max_seq_length=2048, num_train_epochs=epochs,
    )
    trainer.train()
    model.save_pretrained(output_dir)
```

**Hardware requirements:**
- **Minimum:** RTX 3090 (24GB VRAM) — QLoRA fits 8B model in ~6GB, training peaks ~16GB
- **Comfortable:** RTX 4090 or A100
- **Cloud fallback:** RunPod/Lambda — ~$0.50-1.00 for a 30-min run
- **No-GPU option:** Cloud fine-tuning APIs (Together AI, Fireworks) — $2-5 per run

### Step 3: Knowledge Extraction (`rlm/personality/extract.py`, ~500 lines)

After training, query the model with structured prompts and generate artifacts:

```python
EXTRACTION_QUERIES = [
    # Technical preferences
    "What programming languages does the user prefer and why?",
    "What testing frameworks and practices does the user favor?",
    "What architectural patterns recur in the user's projects?",
    "How does the user feel about type systems and static analysis?",
    "What are the user's opinions on external dependencies?",

    # Working patterns
    "How does the user typically approach debugging?",
    "What does the user prioritize in code reviews?",
    "How does the user plan and break down large tasks?",
    "What level of detail does the user expect in explanations?",
    "How does the user handle technical disagreements?",

    # Project context
    "What are the user's active projects and their status?",
    "What technical decisions has the user made recently?",
    "What problems is the user currently trying to solve?",
    "What is the user's long-term technical vision?",

    # Communication style
    "How formal or informal is the user's communication?",
    "Does the user prefer concise or detailed responses?",
    "How does the user express approval or dissatisfaction?",
    "What kind of humor or tone does the user respond to?",
]

def extract_knowledge(adapter_path, output_dir):
    """Query personality model and generate artifacts."""

    model = load_model_with_adapter(adapter_path)

    knowledge = {}
    for query in EXTRACTION_QUERIES:
        knowledge[query] = model.generate(query, max_tokens=500)

    # Artifact 1: USER_PROFILE.md (injected at SessionStart)
    profile = synthesize_profile(knowledge)
    write_file(f"{output_dir}/USER_PROFILE.md", profile)

    # Artifact 2: Structured facts → facts table
    facts = extract_atomic_facts(knowledge)
    for fact in facts:
        db.insert_fact(fact)

    # Artifact 3: Pattern observations → entries table
    patterns = synthesize_patterns(knowledge)
    memory.add_memory(
        content=patterns,
        tags=["personality", "auto-extracted", "patterns"],
        summary="Auto-extracted user patterns and preferences"
    )
```

**Example output — `~/.rlm/personality/USER_PROFILE.md`:**

```markdown
## User Profile (auto-generated 2026-02-20)

### Technical Identity
- Primary languages: Python, TypeScript
- Prefers functional patterns over OOP
- Strong opinions on testing: pytest, integration > unit tests
- Values zero-dependency designs, considers each dependency a liability

### Working Style
- Debugs by reading code first, then adding targeted logging
- Plans in broad strokes, iterates quickly on implementation
- Prefers short responses with code over long explanations
- Wants architectural rationale, not just "here's the code"

### Current Context
- Building RLM: recursive language model system for Claude Code
- Focused on memory architecture and recall precision
- Active exploration of parametric memory via fine-tuning

### Communication
- Direct, low-ceremony, values candor
- Appreciates when assumptions are stated explicitly
- Pushes back on over-engineering — "three similar lines > premature abstraction"
- Engages deeply with novel ideas, will riff on concepts across sessions
```

### Step 4: Integration with Existing RLM (~300 lines)

**New CLI subcommands:**

```bash
rlm personality build-dataset   # Step 1: Generate Q&A pairs from transcripts
rlm personality train           # Step 2: Fine-tune LoRA adapter
rlm personality extract         # Step 3: Query model, generate artifacts
rlm personality run             # All 3 steps in sequence
rlm personality status          # Show adapter age, last run, stats
```

**`hooks/session-start-rlm.py` modification:**

```python
# Current: inject 3 recent session summaries
# New: ALSO inject USER_PROFILE.md if it exists

profile_path = os.path.expanduser("~/.rlm/personality/USER_PROFILE.md")
if os.path.exists(profile_path):
    profile = read_file(profile_path)
    context += f"\n\n{profile}"
```

**`mcp/server.py` — optional live query tool:**

```python
# rlm_personality_query — only registered if adapter exists AND Ollama is running
# For users who want live queries during sessions (requires GPU)
{
    "name": "rlm_personality_query",
    "description": "Query the personality model about user patterns (requires local GPU)",
    "inputSchema": {
        "properties": {
            "question": {"type": "string", "description": "Question about user preferences/patterns"}
        },
        "required": ["question"]
    }
}
```

### Step 5: Evaluation Framework (`rlm/personality/eval.py`, ~200 lines)

This is the hardest question: **how do you measure if this works?**

```python
def evaluate_personality_model(adapter_path, test_transcripts):
    """Evaluate personality model quality."""

    # 1. Holdout test: train on sessions 1-25, test on 26-30
    #    Ask questions about patterns visible in sessions 26-30
    #    Measure: does the model capture patterns from training data
    #    that are confirmed in held-out data?

    # 2. A/B profile comparison:
    #    Generate USER_PROFILE.md from the fine-tuned model
    #    Generate USER_PROFILE.md from simple keyword extraction
    #    User rates which is more accurate and useful

    # 3. Fact precision/recall:
    #    Extract facts from model
    #    Compare against manually labeled facts
    #    Measure overlap and false positive rate

    # 4. Session quality (long-term):
    #    Compare user satisfaction in sessions with vs. without profile injection
    #    Measure: does Claude give better-tailored responses?
```

## Engineering Effort Summary

| Component | New Code | Effort |
|---|---|---|
| Training data pipeline (`personality/dataset.py`) | ~800-1000 lines | 2 weeks |
| Fine-tuning orchestration (`personality/train.py`) | ~400 lines | 1 week |
| Knowledge extraction (`personality/extract.py`) | ~500 lines | 1 week |
| CLI + hooks + MCP integration | ~300 lines | 3-4 days |
| Evaluation framework (`personality/eval.py`) | ~200 lines | 3-4 days |
| **Total** | **~2200-2400 lines** | **~5-6 weeks** |

## Ongoing Costs

| Resource | Monthly Cost |
|---|---|
| Claude Haiku batch API (Q&A generation from 30 transcripts) | ~$0.50 |
| GPU time for LoRA training (30 min cloud) | ~$0.50-1.00 |
| Local inference for extraction (Ollama, 50 queries) | Free |
| **Total** | **~$1-2/month** |

## What you get vs. what you already have

**Without personality layer (current RLM):**
- SessionStart injects: 3 most recent session summaries for this project
- Recall finds: episodes matching keyword queries
- Blind spots: implicit preferences, working patterns, cross-project knowledge

**With personality layer:**
- SessionStart injects: project summaries **+ rich user profile** (preferences, style, patterns)
- Recall finds: episodes **+ structured facts extracted from patterns**
- New capability: the system "knows" things the user never explicitly stated, inferred from behavioral patterns across hundreds of sessions

## Key Risks

1. **Training data quality** — The Q&A generation prompt (Step 1) is make-or-break. If Claude generates generic pairs ("user likes clean code"), the fine-tuned model will be useless. This needs careful iteration.
2. **8B model expressiveness** — A small model may not capture subtle patterns well enough to justify the pipeline complexity. Needs empirical validation.
3. **Evaluation difficulty** — "It feels like it knows me" is hard to quantify. Need concrete metrics before investing heavily.
4. **GPU accessibility** — Limits adoption to users with local GPU or willingness to use cloud compute.
5. **Marginal value** — If structured fact extraction (separate issue) captures 90% of the value, the additional complexity of fine-tuning may not be justified.

## Recommended First Step

**Manual proof-of-concept before building anything.** Take 5 archived transcripts, feed them to Claude with the extraction prompt, review the Q&A pairs, and assess:
- Are the generated pairs **specific and surprising** (capturing things you recognize as true but never explicitly said)?
- Or are they **generic platitudes** that any developer profile would match?

If the former, the approach is viable. If the latter, fine-tuning won't help and we should focus engineering effort on structured fact extraction instead.

## Dependencies

- **Structured fact extraction** (separate issue) should be implemented first — the personality layer generates facts that need somewhere to go
- **Python dependencies:** `unsloth`, `transformers`, `peft`, `trl` (only needed for training, not runtime)
- **Optional:** Ollama for local model serving during extraction

## References

- Conversation about time-sharded fine-tuning as memory (led to this scoped-down approach)
- [@rohit4verse's X post](https://x.com/rohit4verse/status/2012925228159295810) — tacit knowledge layer concept in agent-memory
- [Martian-Engineering/agent-memory](https://github.com/Martian-Engineering/agent-memory) — MEMORY.md as a "how your human operates" layer
- [Unsloth](https://github.com/unslothai/unsloth) — 2x faster LoRA fine-tuning
- [QLoRA paper](https://arxiv.org/abs/2305.14314) — 4-bit quantized fine-tuning for consumer hardware

## Labels

`enhancement`, `memory`, `exploration`, `phase-5`
