"""Claude provider for RLM subagent analysis.

This provider is a lightweight shim for the Claude Code Task subagent
approach. When running inside Claude Code, the orchestration in SKILL.md
dispatches subagents natively via the Task tool -- no API calls needed.

This provider exists so that `rlm analyze` can also work via the
Anthropic Messages API for use outside of Claude Code (e.g., in scripts
or other agent frameworks).

Configuration via environment variables:
    ANTHROPIC_API_KEY - Required when using API mode.
    RLM_MODEL         - Optional. Override the default model (default: claude-haiku-4-5-20251001).
"""

import json
import os
import urllib.request
import urllib.error

from rlm.providers.base import Provider

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"

SYSTEM_PROMPT = """\
You are a code analysis assistant. You will be given a chunk of code or text \
and a query to analyze it against. Provide structured findings.

Return your findings in this format:
- Finding: <description>
- Location: <file:line if applicable>
- Severity/Relevance: <high/medium/low>
- Details: <explanation>

If nothing relevant is found, say "No findings for this chunk."

Be concise and precise. Focus only on what the query asks about."""


class ClaudeProvider(Provider):
    """Anthropic Claude API provider using stdlib urllib."""

    @property
    def name(self) -> str:
        return "claude"

    @property
    def default_model(self) -> str:
        return DEFAULT_MODEL

    def analyze(self, content: str, query: str, context: str = "") -> str:
        """Call Anthropic Messages API to analyze content."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return (
                "Error: ANTHROPIC_API_KEY environment variable is not set. "
                "When running inside Claude Code, use Task subagents instead "
                "of `rlm analyze`. The API key is only needed for standalone use."
            )

        base_url = os.environ.get("ANTHROPIC_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        model = self.get_model()

        user_message = f"Query: {query}\n"
        if context:
            user_message += f"Context: {context}\n"
        user_message += f"\nContent to analyze:\n{content}"

        payload = {
            "model": model,
            "max_tokens": 2000,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": user_message},
            ],
        }

        url = f"{base_url}/v1/messages"
        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": API_VERSION,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                # Anthropic returns content as a list of blocks
                blocks = result.get("content", [])
                text_parts = [b["text"] for b in blocks if b.get("type") == "text"]
                return "\n".join(text_parts) if text_parts else "No response content"
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            return f"Error: Anthropic API returned {e.code}: {body[:500]}"
        except urllib.error.URLError as e:
            return f"Error: Failed to reach Anthropic API: {e.reason}"
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return f"Error: Unexpected API response format: {e}"
