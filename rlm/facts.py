"""Structured fact extraction from conversation transcripts.

Extracts discrete facts, decisions, preferences, and relationships
from archived conversations using LLM (Claude CLI).

Each fact is an atomic, independently queryable piece of knowledge.
"""

import json
import re
import subprocess
import sys
import time
import uuid
from typing import List

from rlm import db

# Valid fact types
FACT_TYPES = {"decision", "preference", "relationship", "technical", "observation"}

# Minimum confidence threshold for fact storage — facts below this are discarded.
# Regex fallback often produces 0.5–0.6 confidence facts that pollute the DB.
MIN_CONFIDENCE = 0.75

# Common English stopwords to filter from entities
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "as", "be", "was", "are",
    "been", "has", "had", "have", "do", "does", "did", "not", "no", "if",
    "so", "up", "out", "that", "this", "then", "than", "its", "my", "your",
    "we", "he", "she", "they", "them", "i", "me", "you", "us", "our",
    "his", "her", "who", "what", "when", "where", "how", "which", "all",
    "each", "every", "any", "some", "can", "will", "just", "about", "also",
}

EXTRACTION_PROMPT = """Analyze this conversation transcript and extract discrete, specific facts.

GOOD facts (specific, actionable, non-obvious):
- "User chose pytest over unittest for the RLM project" (decision)
- "User prefers zero external dependencies in Python projects" (preference)
- "Project RLM uses SQLite FTS5 for memory search, not vector embeddings" (technical)
- "User considers over-engineering a bigger risk than under-engineering" (preference)
- "Mark works with Jeff who has go-to-market connections at AWS" (relationship)
- "Mark performs live electronic music as the Cool Cool duo" (observation)
- "Sarah introduced the team to Terraform for infrastructure management" (relationship)

BAD facts (generic, obvious, useless — NEVER extract these):
- "User likes clean code" (too vague)
- "User is working on a software project" (obvious from context)
- "User uses Python" (too generic)
- "The assistant helped with code" (describes the conversation itself)
- "Click the settings icon and select Preferences" (UI instruction)
- "Run pip install -r requirements.txt to install dependencies" (setup step)
- "According to the docs, the API returns a JSON response" (quoted documentation)
- "The function takes two arguments and returns a string" (code description)

NEVER extract: UI instructions, setup steps, installation commands, quoted documentation,
or descriptions of what code does. Only extract facts about the USER, their projects,
their relationships, and their decisions.

ENTITY RULES — the entity field must be one of:
- A proper noun (e.g. "Mark", "Sarah")
- A project name (e.g. "rlm", "openclaw")
- A tool or technology name (e.g. "pytest", "sqlite", "terraform")
- An organization name (e.g. "AWS", "Anthropic")
Entities must NEVER be common English words like "the", "idea", "code", "project",
"function", "data", "user", or "system". If no specific entity fits, use the most
specific proper noun or tool name mentioned.

For each fact, return a JSON array of objects with these fields:
- fact_text: The atomic fact (one sentence, specific)
- entity: Primary entity (MUST be a proper noun, project name, or tool name — see rules above)
- fact_type: one of [decision, preference, relationship, technical, observation]
- confidence: 0.0-1.0 (how confident based on transcript evidence)

Return ONLY the JSON array, no explanation or markdown.

Example output:
[
  {{"fact_text": "User chose SQLite FTS5 over vector embeddings for memory search", "entity": "sqlite", "fact_type": "decision", "confidence": 0.95}},
  {{"fact_text": "Project RLM uses two-tier storage: summary for search + transcript for drill-down", "entity": "rlm", "fact_type": "technical", "confidence": 0.9}},
  {{"fact_text": "Mark works with Jeff who has go-to-market connections at AWS", "entity": "mark", "fact_type": "relationship", "confidence": 0.85}},
  {{"fact_text": "Mark performs live electronic music as the Cool Cool duo", "entity": "mark", "fact_type": "observation", "confidence": 0.9}}
]

Conversation transcript:
---
{transcript}
---

JSON facts array:"""


def _clean_entity(raw: str) -> str | None:
    """Normalize and filter a raw entity string.

    Returns None if the entity is empty, too short, or a stopword.
    """
    entity = raw.strip().lower()
    if len(entity) < 2:
        return None
    if entity in STOPWORDS:
        return None
    return entity


def extract_facts_from_transcript(
    transcript: str,
    source_entry_id: str,
    max_chars: int = 12000,
) -> list[dict]:
    """Extract structured facts from a conversation transcript.

    Args:
        transcript: The conversation transcript text.
        source_entry_id: The memory entry ID this transcript belongs to.
        max_chars: Max chars to send to LLM.

    Returns:
        List of fact dicts ready for db.insert_fact().
    """
    # Truncate long transcripts (head 60% + tail 40%)
    if len(transcript) > max_chars:
        head_size = int(max_chars * 0.6)
        tail_size = max_chars - head_size
        truncated = transcript[:head_size] + "\n...[middle truncated]...\n" + transcript[-tail_size:]
    else:
        truncated = transcript

    raw_facts = _extract_via_llm(truncated)
    if raw_facts is None:
        raw_facts = []

    # Normalize and prepare for storage
    now = time.time()
    results = []
    for raw in raw_facts:
        fact_text = raw.get("fact_text", "").strip()
        if not fact_text or len(fact_text) < 10:
            continue

        fact_type = raw.get("fact_type", "observation").lower()
        if fact_type not in FACT_TYPES:
            fact_type = "observation"

        confidence = raw.get("confidence", 0.8)
        if not isinstance(confidence, (int, float)):
            confidence = 0.8
        confidence = max(0.0, min(1.0, float(confidence)))

        if confidence < MIN_CONFIDENCE:
            continue

        entity = _clean_entity(raw.get("entity", ""))

        fact_id = "f_" + uuid.uuid4().hex[:12]

        results.append({
            "fact_id": fact_id,
            "fact_text": fact_text,
            "source_entry_id": source_entry_id,
            "entity": entity,
            "fact_type": fact_type,
            "confidence": confidence,
            "created_at": now,
        })

    return results


def store_facts(facts: list[dict]) -> int:
    """Store extracted facts in the database, with contradiction detection.

    Returns count of facts stored.
    """
    stored = 0
    for fact in facts:
        # Check for contradictions with existing facts
        if fact.get("entity"):
            existing = db.find_facts_by_entity(
                fact["entity"], fact_type=fact["fact_type"]
            )
            for old in existing:
                # Supersede older facts with same entity + type
                db.supersede_fact(old["id"], fact["fact_id"])

        db.insert_fact(
            fact_id=fact["fact_id"],
            fact_text=fact["fact_text"],
            source_entry_id=fact["source_entry_id"],
            entity=fact.get("entity"),
            fact_type=fact["fact_type"],
            confidence=fact["confidence"],
            created_at=fact["created_at"],
        )
        stored += 1

    return stored


def _extract_via_llm(transcript: str) -> list[dict] | None:
    """Try to extract facts via Claude CLI or API. Returns None on failure."""
    prompt = EXTRACTION_PROMPT.format(transcript=transcript)

    try:
        # Approach 1: Claude CLI
        try:
            result = subprocess.run(
                ["claude", "-p"],
                input=prompt,
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
            response = result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Approach 2: Anthropic API if key is set
            import os
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                return None

            import urllib.request
            import urllib.error

            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            data = json.dumps({
                "model": "claude-3-haiku-20240307",
                "max_tokens": 2000,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()

            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=data,
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    body = json.loads(resp.read())
                    response = body["content"][0]["text"]
            except (urllib.error.URLError, KeyError, json.JSONDecodeError):
                return None

        return _parse_llm_response(response)

    except Exception as e:
        print(f"[Facts] LLM extraction failed: {e}", file=sys.stderr)
        return None


def _parse_llm_response(response: str) -> list[dict]:
    """Parse the LLM response into a list of fact dicts."""
    # Strip markdown code fences if present
    response = response.strip()
    if response.startswith("```"):
        lines = response.split("\n")
        # Remove first and last lines (the fences)
        lines = [l for l in lines if not l.strip().startswith("```")]
        response = "\n".join(lines)

    try:
        facts = json.loads(response)
        if isinstance(facts, list):
            return facts
    except json.JSONDecodeError:
        # Try to find a JSON array in the response
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            try:
                facts = json.loads(match.group())
                if isinstance(facts, list):
                    return facts
            except json.JSONDecodeError:
                pass

    return []


def _extract_fallback(transcript: str) -> list[dict]:
    """Keyword-based fallback — disabled, returns empty list.

    The regex patterns produced more noise than signal: generic phrases like
    'selected X' and 'using X instead of Y' matched UI instructions and setup
    steps rather than real user decisions.  Better to extract nothing than
    garbage facts.  See https://github.com/marknutter/recursive-ai/issues/50.
    """
    return []


def format_facts(facts: list[dict], max_chars: int = 4000) -> str:
    """Format facts into human-readable output."""
    if not facts:
        return "No facts found."

    lines = [f"Facts ({len(facts)}):\n"]
    for f in facts:
        entity = f.get("entity") or "—"
        conf = f.get("confidence", 0)
        superseded = " [superseded]" if f.get("superseded_by") else ""
        score = f" (score: {f['score']:.1f})" if "score" in f else ""

        line = f"  [{f['fact_type']}] {f['fact_text']}"
        line += f"  (entity: {entity}, conf: {conf:.0%}{superseded}{score})"
        lines.append(line)

        if len("\n".join(lines)) > max_chars - 100:
            remaining = len(facts) - len(lines) + 1
            if remaining > 0:
                lines.append(f"\n  ... and {remaining} more facts")
            break

    return "\n".join(lines)
