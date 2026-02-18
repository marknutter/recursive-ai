#!/usr/bin/env python3
"""
Semantic tag extraction for conversations using LLM.

Generates meaningful tags from conversation transcripts to improve
memory recall quality.
"""

import json
import subprocess
import sys
from typing import List

# Tag extraction prompt
TAG_PROMPT = """Analyze this conversation transcript and extract 5-10 semantic tags.

Focus on:
- Technical topics discussed (e.g., sqlite, hooks, mcp-server)
- Specific features or components mentioned (e.g., authentication, caching, api)
- Technologies and tools used (e.g., python, typescript, docker)
- Types of work done (e.g., debugging, architecture-decision, refactoring, testing)
- Key decisions or solutions reached (e.g., performance-optimization, bug-fix)

Return ONLY a comma-separated list of lowercase tags, no explanation.
Keep tags specific and meaningful for future search.

Example output:
sqlite,hooks,memory-optimization,architecture-decision,python,debugging,performance

Conversation transcript:
---
{transcript}
---

Tags:"""


def extract_semantic_tags(transcript: str, max_chars: int = 10000) -> List[str]:
    """
    Extract semantic tags from a conversation transcript using Claude.

    Args:
        transcript: The conversation transcript to analyze
        max_chars: Maximum characters to send to LLM (default 10000)

    Returns:
        List of semantic tags
    """
    # Truncate very long transcripts to avoid token limits
    # Focus on beginning and end which usually have the most context
    if len(transcript) > max_chars:
        # Take first 60% and last 40% of the allowed chars
        head_size = int(max_chars * 0.6)
        tail_size = max_chars - head_size
        truncated = transcript[:head_size] + "\n...[middle truncated]...\n" + transcript[-tail_size:]
    else:
        truncated = transcript

    prompt = TAG_PROMPT.format(transcript=truncated)

    try:
        # Try multiple approaches to call an LLM

        # Approach 1: Try claude CLI (if available)
        try:
            result = subprocess.run(
                ["claude", "--no-conversation"],
                input=prompt,
                capture_output=True,
                text=True,
                check=True,
                timeout=30
            )
            response = result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Approach 2: Try using curl to call Claude API directly if API key is set
            import os
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if api_key:
                import requests
                headers = {
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                }
                data = {
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": prompt}]
                }
                resp = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers=headers,
                    json=data,
                    timeout=30
                )
                if resp.status_code == 200:
                    response = resp.json()["content"][0]["text"]
                else:
                    raise Exception(f"API call failed: {resp.status_code}")
            else:
                # Approach 3: Fallback to simple keyword extraction
                return extract_keywords_fallback(transcript)

        # Clean up the response
        # Remove any markdown formatting, quotes, or explanations
        if "```" in response:
            # Extract content between backticks if present
            lines = response.split('\n')
            response = [l for l in lines if not l.startswith('```')][0] if lines else response

        # Split and clean tags
        tags = [tag.strip().lower() for tag in response.split(',')]

        # Filter out empty tags and common noise words
        noise_words = {'the', 'and', 'or', 'but', 'with', 'for', 'to', 'in', 'on', 'at'}
        tags = [t for t in tags if t and len(t) > 2 and t not in noise_words]

        # Limit to 10 tags max
        return tags[:10]

    except Exception as e:
        print(f"[SemanticTags] Using fallback keyword extraction: {e}", file=sys.stderr)
        return extract_keywords_fallback(transcript)


def extract_keywords_fallback(transcript: str) -> List[str]:
    """
    Simple fallback keyword extraction when LLM is not available.

    Extracts common technical terms and patterns from the transcript.
    """
    import re

    # Common technical keywords to look for
    tech_keywords = {
        'mcp', 'hook', 'hooks', 'memory', 'recall', 'sqlite', 'database',
        'api', 'authentication', 'auth', 'testing', 'test', 'debugging',
        'performance', 'optimization', 'refactoring', 'architecture',
        'python', 'javascript', 'typescript', 'react', 'node', 'docker',
        'git', 'github', 'commit', 'branch', 'merge', 'pull-request',
        'bug', 'fix', 'feature', 'implementation', 'deployment',
        'server', 'client', 'frontend', 'backend', 'middleware',
        'cache', 'caching', 'session', 'semantic', 'tagging', 'tags'
    }

    # Extract words from transcript
    words = re.findall(r'\b[a-z]+(?:-[a-z]+)*\b', transcript.lower())
    word_freq = {}

    for word in words:
        if word in tech_keywords and len(word) > 2:
            word_freq[word] = word_freq.get(word, 0) + 1

    # Sort by frequency and return top tags
    sorted_tags = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
    tags = [tag for tag, _ in sorted_tags[:10]]

    # Add some contextual tags based on patterns
    if 'bug' in transcript.lower() or 'fix' in transcript.lower():
        if 'bug-fix' not in tags:
            tags.append('bug-fix')
    if 'test' in transcript.lower():
        if 'testing' not in tags:
            tags.append('testing')
    if 'refactor' in transcript.lower():
        if 'refactoring' not in tags:
            tags.append('refactoring')

    return tags[:10]


def combine_tags(base_tags: str, semantic_tags: List[str]) -> str:
    """
    Combine base tags with semantic tags, avoiding duplicates.

    Args:
        base_tags: Existing comma-separated tags (e.g., "conversation,session,project,date")
        semantic_tags: List of semantic tags to add

    Returns:
        Combined comma-separated tag string
    """
    # Parse existing tags
    existing = set(tag.strip() for tag in base_tags.split(','))

    # Add semantic tags that aren't duplicates
    all_tags = list(existing)
    for tag in semantic_tags:
        if tag and tag not in existing:
            all_tags.append(tag)

    return ','.join(all_tags)


if __name__ == "__main__":
    # Test the tag extraction
    test_transcript = """
    User: I need help setting up authentication for my API
    Assistant: I'll help you set up authentication. Let me first check your current setup...
    [Tool: Read] Checking package.json
    [Tool: Read] Looking at auth middleware
    Assistant: I see you're using Express. Let's implement JWT authentication.
    [Tool: Write] Created auth.js with JWT validation
    [Tool: Write] Added bcrypt for password hashing
    User: Great! Now how do I test this?
    Assistant: Let me create some tests for the auth endpoints...
    [Tool: Write] Created auth.test.js with Jest tests
    """

    print("Testing semantic tag extraction...")
    tags = extract_semantic_tags(test_transcript)
    print(f"Extracted tags: {tags}")