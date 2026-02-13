"""OpenRouter adapter — access any model via the OpenRouter API.

Uses the OpenAI-compatible chat completions endpoint at
https://openrouter.ai/api/v1/chat/completions.

Requires OPENROUTER_API_KEY environment variable.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

import httpx

from llm.adapter import LLMAdapter

log = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class OpenRouterAdapter(LLMAdapter):
    """Adapter for OpenRouter's OpenAI-compatible API."""

    def __init__(
        self,
        model: str = "google/gemini-2.5-flash",
        api_key: str | None = None,
        base_url: str = OPENROUTER_BASE,
        timeout: float = 60.0,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        if not self._api_key:
            log.warning("OPENROUTER_API_KEY not set — LLM calls will fail.")

    @property
    def name(self) -> str:
        return f"openrouter/{self._model}"

    @property
    def supports_embeddings(self) -> bool:
        return False  # OpenRouter doesn't expose embedding endpoints

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        response_format: Optional[str] = None,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
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
        log.debug(f"OpenRouter request: model={self._model}, tokens={max_tokens}")

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                log.debug(f"OpenRouter response ({len(content)} chars)")
                return content
        except httpx.HTTPStatusError as e:
            log.error(
                f"OpenRouter HTTP error: {e.response.status_code} — {e.response.text[:200]}"
            )
            raise
        except Exception as e:
            log.error(f"OpenRouter error: {e}")
            raise

    def embed(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError("OpenRouter does not support embeddings directly.")
