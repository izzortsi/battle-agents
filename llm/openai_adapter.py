"""OpenAI adapter — direct access to the OpenAI API.

Uses the chat completions endpoint at https://api.openai.com/v1/chat/completions
and the embeddings endpoint at https://api.openai.com/v1/embeddings.

Requires OPENAI_API_KEY environment variable.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

import httpx

from llm.adapter import LLMAdapter

log = logging.getLogger(__name__)

OPENAI_BASE = "https://api.openai.com/v1"


class OpenAIAdapter(LLMAdapter):
    """Adapter for the OpenAI API (GPT-4o, o3, etc.)."""

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str = OPENAI_BASE,
        timeout: float = 60.0,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        if not self._api_key:
            log.warning("OPENAI_API_KEY not set — LLM calls will fail.")

    @property
    def name(self) -> str:
        return f"openai/{self._model}"

    @property
    def supports_embeddings(self) -> bool:
        return True

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        response_format: Optional[str] = None,
    ) -> str:
        payload: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        url = f"{self._base_url}/chat/completions"
        log.debug(f"OpenAI request: model={self._model}, tokens={max_tokens}")

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(url, headers=self._headers(), json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                log.debug(f"OpenAI response ({len(content)} chars)")
                return content
        except httpx.HTTPStatusError as e:
            log.error(
                f"OpenAI HTTP error: {e.response.status_code} — {e.response.text[:200]}"
            )
            raise
        except Exception as e:
            log.error(f"OpenAI error: {e}")
            raise

    def embed(self, texts: List[str]) -> List[List[float]]:
        payload = {"model": "text-embedding-3-small", "input": texts}
        url = f"{self._base_url}/embeddings"
        log.debug(f"OpenAI embed: {len(texts)} texts")

        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(url, headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()

        results = sorted(data["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in results]

    async def async_complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        response_format: Optional[str] = None,
    ) -> str:
        """Native async completion using httpx.AsyncClient."""
        payload: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        url = f"{self._base_url}/chat/completions"
        log.debug(f"OpenAI async request: model={self._model}, tokens={max_tokens}")

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, headers=self._headers(), json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                log.debug(f"OpenAI async response ({len(content)} chars)")
                return content
        except httpx.HTTPStatusError as e:
            log.error(
                f"OpenAI HTTP error: {e.response.status_code} — {e.response.text[:200]}"
            )
            raise
        except Exception as e:
            log.error(f"OpenAI async error: {e}")
            raise

    async def async_embed(self, texts: List[str]) -> List[List[float]]:
        """Native async embedding using httpx.AsyncClient."""
        payload = {"model": "text-embedding-3-small", "input": texts}
        url = f"{self._base_url}/embeddings"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()

        results = sorted(data["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in results]
