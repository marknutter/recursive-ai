"""OpenAI provider for RLM subagent analysis.

Uses stdlib urllib to call the OpenAI Chat Completions API.
No external dependencies required.

Supports models: codex-mini-latest, gpt-4o-mini, gpt-4o, o3-mini, o4-mini, etc.

Configuration via environment variables:
    OPENAI_API_KEY  - Required. Your OpenAI API key.
    RLM_MODEL       - Optional. Override the default model.
    OPENAI_BASE_URL - Optional. Override the API base URL.
"""

import json
import os
import urllib.request
import urllib.error

from rlm.providers.base import Provider

DEFAULT_MODEL = "codex-mini-latest"
DEFAULT_BASE_URL = "https://api.openai.com/v1"

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


class OpenAIProvider(Provider):
    """OpenAI API provider using stdlib urllib."""

    @property
    def name(self) -> str:
        return "openai"

    @property
    def default_model(self) -> str:
        return DEFAULT_MODEL

    def analyze(self, content: str, query: str, context: str = "") -> str:
        """Call OpenAI API to analyze content."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return "Error: OPENAI_API_KEY environment variable is not set"

        base_url = os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
        model = self.get_model()

        user_message = f"Query: {query}\n"
        if context:
            user_message += f"Context: {context}\n"
        user_message += f"\nContent to analyze:\n{content}"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0,
            "max_tokens": 2000,
        }

        url = f"{base_url}/chat/completions"
        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            return f"Error: OpenAI API returned {e.code}: {body[:500]}"
        except urllib.error.URLError as e:
            return f"Error: Failed to reach OpenAI API: {e.reason}"
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return f"Error: Unexpected API response format: {e}"
