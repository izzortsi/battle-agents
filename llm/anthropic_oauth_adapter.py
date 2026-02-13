"""Anthropic OAuth adapter — access Claude via Pro/Max subscription.

Uses the anthropic-oauth library for OAuth PKCE authentication, enabling
$0-cost inference through a Claude Pro or Max subscription.

Requires anthropic-oauth to be installed and tokens to be available
(run `python -m anthropic_oauth` to authenticate interactively).

The adapter calls the Anthropic Messages API directly via httpx with
the OAuthTransport handling auth headers and request transformations.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

import httpx

from llm.adapter import LLMAdapter

log = logging.getLogger(__name__)

ANTHROPIC_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicOAuthAdapter(LLMAdapter):
    """Adapter for Anthropic Claude models via OAuth (Pro/Max subscription)."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-5-20250929",
        token_path: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._model = model
        self._token_path = token_path
        self._timeout = timeout
        self._transport: httpx.BaseTransport | None = None
        self._async_transport: httpx.AsyncBaseTransport | None = None

    def _get_transport(self) -> httpx.BaseTransport:
        """Lazy-init the OAuth transport (avoids import at module load)."""
        if self._transport is None:
            try:
                from anthropic_oauth import OAuthManager, OAuthTransport, RequestTransformer
            except ImportError:
                raise ImportError(
                    "anthropic-oauth is required for the Anthropic OAuth adapter. "
                    "Install it from: /home/istrozzi/Documents/GitHub/anthropic-oauth"
                )

            kwargs = {}
            if self._token_path:
                kwargs["token_path"] = self._token_path
            manager = OAuthManager(**kwargs)

            if not manager.has_valid_tokens():
                raise RuntimeError(
                    "No valid Anthropic OAuth tokens found. "
                    "Run `python -m anthropic_oauth` to authenticate."
                )

            transformer = RequestTransformer(app_names=["Battle-Agents"])
            self._transport = OAuthTransport(manager, transformer=transformer)
        return self._transport

    @property
    def name(self) -> str:
        return f"anthropic/{self._model}"

    @property
    def supports_embeddings(self) -> bool:
        return False

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        response_format: Optional[str] = None,
    ) -> str:
        transport = self._get_transport()

        payload: dict = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [
                {"role": "user", "content": user},
            ],
        }

        url = f"{ANTHROPIC_BASE}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
        }
        log.debug(f"Anthropic OAuth request: model={self._model}, tokens={max_tokens}")

        try:
            with httpx.Client(transport=transport, timeout=self._timeout) as client:
                resp = client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                # Anthropic Messages API returns content as array of blocks
                content = ""
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        content += block["text"]
                log.debug(f"Anthropic OAuth response ({len(content)} chars)")
                return content
        except httpx.HTTPStatusError as e:
            log.error(
                f"Anthropic HTTP error: {e.response.status_code} — {e.response.text[:200]}"
            )
            raise
        except Exception as e:
            log.error(f"Anthropic OAuth error: {e}")
            raise

    def embed(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError(
            "Anthropic does not support embeddings. "
            "Use OpenAI or OpenRouter for embeddings."
        )

    async def async_complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        response_format: Optional[str] = None,
    ) -> str:
        """Async completion — delegates to thread since OAuthTransport is sync."""
        import asyncio

        return await asyncio.to_thread(
            self.complete, system, user, max_tokens, temperature, response_format
        )
