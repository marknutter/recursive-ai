"""LLM provider registry for RLM subagent analysis.

Supports multiple providers for chunk analysis. Provider is selected
via the RLM_PROVIDER environment variable (default: "claude").

Available providers:
- claude: Uses Claude Code Task subagents (no API key needed)
- openai: Uses OpenAI API (requires OPENAI_API_KEY)
"""

import os

from rlm.providers.base import Provider


def get_provider(name: str | None = None) -> Provider:
    """Get a provider instance by name.

    Falls back to RLM_PROVIDER env var, then to "claude".
    """
    name = name or os.environ.get("RLM_PROVIDER", "claude")
    name = name.lower().strip()

    if name == "openai" or name == "codex":
        from rlm.providers.openai_provider import OpenAIProvider
        return OpenAIProvider()
    elif name == "claude":
        from rlm.providers.claude_provider import ClaudeProvider
        return ClaudeProvider()
    else:
        raise ValueError(
            f"Unknown provider: {name!r}. "
            f"Supported: claude, openai"
        )


def list_providers() -> list[str]:
    """List available provider names."""
    return ["claude", "openai"]
