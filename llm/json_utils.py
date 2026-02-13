"""Robust JSON extraction from LLM responses.

LLMs often wrap JSON in markdown code fences or add preamble text.
This module provides reliable extraction with multiple fallback strategies.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# Patterns to find JSON in LLM output (ordered by specificity)
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

# Trailing comma before } or ] — very common LLM mistake
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _clean_json(text: str) -> str:
    """Remove trailing commas — a very common LLM JSON error."""
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _try_parse(text: str) -> Any | None:
    """Try json.loads, then retry with trailing-comma cleanup."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    cleaned = _clean_json(text)
    if cleaned != text:
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
    return None


def _find_object_brace_match(text: str, start: int = 0) -> str | None:
    """Find the outermost { ... } from *start*, respecting string literals.

    Tracks whether we are inside a JSON string (between unescaped quotes)
    so that braces inside string values don't break the depth count.
    """
    obj_start = text.find("{", start)
    if obj_start == -1:
        return None

    depth = 0
    in_string = False
    i = obj_start
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\" :
                i += 2  # skip escaped char
                continue
            if ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[obj_start : i + 1]
        i += 1
    return None


def extract_json(text: str) -> Any:
    """Extract JSON from LLM output using multiple strategies.

    Strategy order:
    1. Direct parse (text is pure JSON), with trailing-comma cleanup
    2. Extract from markdown code fence (```json ... ```)
    3. Find first balanced JSON object { ... } in text (string-aware)
    4. Find first JSON array [ ... ] in text

    Raises ValueError if no valid JSON can be extracted.
    """
    text_stripped = text.strip()

    # Strategy 1: direct parse
    result = _try_parse(text_stripped)
    if result is not None:
        return result

    # Strategy 2: markdown code fence
    match = _JSON_BLOCK_RE.search(text)
    if match:
        result = _try_parse(match.group(1).strip())
        if result is not None:
            return result

    # Strategy 3: string-aware brace matching for nested objects
    candidate = _find_object_brace_match(text)
    if candidate:
        result = _try_parse(candidate)
        if result is not None:
            return result

    # Strategy 4: first JSON array
    match = _JSON_ARRAY_RE.search(text)
    if match:
        result = _try_parse(match.group(0))
        if result is not None:
            return result

    raise ValueError(f"Could not extract JSON from LLM output: {text[:200]}...")
