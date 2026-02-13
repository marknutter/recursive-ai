"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod


class Provider(ABC):
    """Base class for LLM providers used in RLM subagent analysis."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'openai', 'claude')."""
        ...

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model for this provider."""
        ...

    @abstractmethod
    def analyze(self, content: str, query: str, context: str = "") -> str:
        """Analyze content for a query and return structured findings.

        Args:
            content: The extracted chunk content to analyze.
            query: The user's analysis query.
            context: Optional context about the chunk (e.g., file path, chunk name).

        Returns:
            Structured findings as a string.
        """
        ...

    def get_model(self) -> str:
        """Get the model to use, respecting RLM_MODEL env override."""
        import os
        return os.environ.get("RLM_MODEL", self.default_model)
