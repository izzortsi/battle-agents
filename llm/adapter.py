"""LLM adapter ABC and dynamic model registry.

The registry maps string keys (e.g. "openrouter/gemini-3-flash") to adapter
instances.  New adapters are registered at startup from config; any adapter
conforming to the ABC can be plugged in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional


class LLMAdapter(ABC):
    """Abstract base for all LLM backends."""

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        response_format: Optional[str] = None,
    ) -> str:
        """Generate a completion.  Returns raw text."""
        ...

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of texts.  Returns list of vectors."""
        ...

    @property
    @abstractmethod
    def supports_embeddings(self) -> bool: ...

    @property
    @abstractmethod
    def name(self) -> str: ...


class ModelRegistry:
    """Dynamic registry mapping model keys to adapter instances.

    Usage:
        registry = ModelRegistry()
        registry.register("openrouter/gemini-3-flash", adapter_instance)
        adapter = registry.get("openrouter/gemini-3-flash")
    """

    def __init__(self) -> None:
        self._adapters: dict[str, LLMAdapter] = {}
        self._default: str | None = None

    def register(self, key: str, adapter: LLMAdapter) -> None:
        self._adapters[key] = adapter
        if self._default is None:
            self._default = key

    def set_default(self, key: str) -> None:
        if key not in self._adapters:
            raise KeyError(f"No adapter registered under '{key}'")
        self._default = key

    def get(self, key: str | None = None) -> LLMAdapter:
        k = key or self._default
        if k is None:
            raise RuntimeError("No adapters registered and no default set.")
        if k not in self._adapters:
            raise KeyError(
                f"No adapter registered under '{k}'. Available: {list(self._adapters.keys())}"
            )
        return self._adapters[k]

    @property
    def available(self) -> list[str]:
        return list(self._adapters.keys())

    def __contains__(self, key: str) -> bool:
        return key in self._adapters

    def __len__(self) -> int:
        return len(self._adapters)
