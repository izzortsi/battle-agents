"""Embedding system — providers, cache, and factory.

Implements the spec §8 embedding architecture:
  - EmbeddingProvider ABC for pluggable backends
  - EmbeddingCache (LRU) wrapping any provider
  - Concrete providers: OpenRouter (primary), OpenAI, Ollama
  - Factory function to create a cache from config

Memories are embedded once at creation time and cached.  Query embeddings
are computed per retrieval call.  Falls back to keyword overlap when no
provider is configured or on transient failures.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Optional

import httpx

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class EmbeddingProvider(ABC):
    """Abstract base for embedding backends."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts.  Returns one vector per input text."""
        ...

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def dimension(self) -> int: ...

    async def async_embed(self, texts: list[str]) -> list[list[float]]:
        """Async version. Default delegates via to_thread."""
        return await asyncio.to_thread(self.embed, texts)


# ---------------------------------------------------------------------------
# LRU cache
# ---------------------------------------------------------------------------


class EmbeddingCache:
    """LRU cache wrapping an EmbeddingProvider.

    This is the primary interface used by the rest of the system.
    """

    def __init__(self, provider: EmbeddingProvider, max_size: int = 2048) -> None:
        self._provider = provider
        self._max_size = max_size
        self._cache: OrderedDict[str, list[float]] = OrderedDict()

    @property
    def provider_name(self) -> str:
        return self._provider.name

    @property
    def dimension(self) -> int:
        return self._provider.dimension

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def embed_one(self, text: str) -> list[float]:
        """Embed a single text, returning from cache if available."""
        key = self._key(text)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        vec = self._provider.embed([text])[0]
        self._put(key, vec)
        return vec

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch, using cache for hits and batching misses."""
        results: list[Optional[list[float]]] = [None] * len(texts)
        miss_indices: list[int] = []
        miss_texts: list[str] = []

        for i, text in enumerate(texts):
            key = self._key(text)
            if key in self._cache:
                self._cache.move_to_end(key)
                results[i] = self._cache[key]
            else:
                miss_indices.append(i)
                miss_texts.append(text)

        if miss_texts:
            vectors = self._provider.embed(miss_texts)
            for idx, vec in zip(miss_indices, vectors):
                self._put(self._key(texts[idx]), vec)
                results[idx] = vec

        return results  # type: ignore[return-value]

    def _put(self, key: str, vec: list[float]) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
            self._cache[key] = vec

    def __len__(self) -> int:
        return len(self._cache)

    # -- Async variants --------------------------------------------------------

    async def async_embed_one(self, text: str) -> list[float]:
        """Async version of embed_one, using cache."""
        key = self._key(text)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        vec = (await self._provider.async_embed([text]))[0]
        self._put(key, vec)
        return vec

    async def async_embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Async version of embed_batch, using cache."""
        results: list[Optional[list[float]]] = [None] * len(texts)
        miss_indices: list[int] = []
        miss_texts: list[str] = []

        for i, text in enumerate(texts):
            key = self._key(text)
            if key in self._cache:
                self._cache.move_to_end(key)
                results[i] = self._cache[key]
            else:
                miss_indices.append(i)
                miss_texts.append(text)

        if miss_texts:
            vectors = await self._provider.async_embed(miss_texts)
            for idx, vec in zip(miss_indices, vectors):
                self._put(self._key(texts[idx]), vec)
                results[idx] = vec

        return results  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Concrete providers
# ---------------------------------------------------------------------------


class OpenRouterEmbeddingProvider(EmbeddingProvider):
    """Embedding via OpenRouter's OpenAI-compatible /embeddings endpoint."""

    def __init__(
        self,
        model: str = "openai/text-embedding-3-small",
        api_key: str | None = None,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 30.0,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._dimension = 1536  # text-embedding-3-small default
        if not self._api_key:
            log.warning("OPENROUTER_API_KEY not set — embedding calls will fail.")

    @property
    def name(self) -> str:
        return f"openrouter/{self._model}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self._model, "input": texts}
        url = f"{self._base_url}/embeddings"
        log.debug(f"OpenRouter embed: {len(texts)} texts, model={self._model}")

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        results = sorted(data["data"], key=lambda d: d["index"])
        vectors = [item["embedding"] for item in results]
        if vectors and len(vectors[0]) != self._dimension:
            self._dimension = len(vectors[0])
        return vectors

    async def async_embed(self, texts: list[str]) -> list[list[float]]:
        """Native async embedding using httpx.AsyncClient."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self._model, "input": texts}
        url = f"{self._base_url}/embeddings"
        log.debug(f"OpenRouter async embed: {len(texts)} texts, model={self._model}")

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        results = sorted(data["data"], key=lambda d: d["index"])
        vectors = [item["embedding"] for item in results]
        if vectors and len(vectors[0]) != self._dimension:
            self._dimension = len(vectors[0])
        return vectors


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Embedding via the OpenAI API directly."""

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._dimension = 1536
        if not self._api_key:
            log.warning("OPENAI_API_KEY not set — embedding calls will fail.")

    @property
    def name(self) -> str:
        return f"openai/{self._model}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self._model, "input": texts}
        url = f"{self._base_url}/embeddings"

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        results = sorted(data["data"], key=lambda d: d["index"])
        vectors = [item["embedding"] for item in results]
        if vectors and len(vectors[0]) != self._dimension:
            self._dimension = len(vectors[0])
        return vectors


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Local embedding via Ollama's /api/embed endpoint."""

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
        timeout: float = 60.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._dimension = 768  # nomic-embed-text default

    @property
    def name(self) -> str:
        return f"ollama/{self._model}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        url = f"{self._base_url}/api/embed"
        payload = {"model": self._model, "input": texts}

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        vectors = data["embeddings"]
        if vectors and len(vectors[0]) != self._dimension:
            self._dimension = len(vectors[0])
        return vectors


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_embedding_cache(
    embedding_cfg: dict,
    llm_cfg: dict,
) -> EmbeddingCache | None:
    """Create an EmbeddingCache from config, or None if disabled.

    Config keys (from the ``embedding`` section of llm_config.yaml):
        provider: "openrouter" | "openai" | "ollama" | "none"
        model:    embedding model ID (optional, provider defaults used)
        cache_size: LRU cache capacity (default 2048)
    """
    provider_name = embedding_cfg.get("provider", "none")
    if provider_name == "none":
        log.info("Embedding provider: none (keyword fallback only)")
        return None

    cache_size = embedding_cfg.get("cache_size", 2048)
    model = embedding_cfg.get("model")

    try:
        provider: EmbeddingProvider

        if provider_name == "openrouter":
            adapters_cfg = llm_cfg.get("adapters", {})
            or_cfg = adapters_cfg.get("openrouter", {})
            api_key_env = or_cfg.get("api_key_env", "OPENROUTER_API_KEY")
            api_key = os.environ.get(api_key_env, "")
            kwargs: dict = {"api_key": api_key}
            if model:
                kwargs["model"] = model
            provider = OpenRouterEmbeddingProvider(**kwargs)

        elif provider_name == "openai":
            kwargs = {}
            if model:
                kwargs["model"] = model
            provider = OpenAIEmbeddingProvider(**kwargs)

        elif provider_name == "ollama":
            kwargs = {}
            if model:
                kwargs["model"] = model
            base_url = embedding_cfg.get("base_url", "http://localhost:11434")
            kwargs["base_url"] = base_url
            provider = OllamaEmbeddingProvider(**kwargs)

        else:
            log.warning(
                f"Unknown embedding provider '{provider_name}', "
                f"falling back to keyword retrieval"
            )
            return None

        cache = EmbeddingCache(provider, max_size=cache_size)
        log.info(
            f"Embedding provider: {provider.name} "
            f"(dim={provider.dimension}, cache={cache_size})"
        )
        return cache

    except Exception as e:
        log.warning(f"Failed to create embedding provider: {e}. Using keyword fallback.")
        return None
