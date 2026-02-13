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
_JSON_OBJECT_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def extract_json(text: str) -> Any:
    """Extract JSON from LLM output using multiple strategies.

    Strategy order:
    1. Direct parse (text is pure JSON)
    2. Extract from markdown code fence (```json ... ```)
    3. Find first JSON object { ... } in text
    4. Find first JSON array [ ... ] in text

    Raises ValueError if no valid JSON can be extracted.
    """
    # Strategy 1: direct parse
    text_stripped = text.strip()
    try:
        return json.loads(text_stripped)
    except json.JSONDecodeError:
        pass

    # Strategy 2: markdown code fence
    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Strategy 3: first JSON object
    match = _JSON_OBJECT_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Strategy 3b: greedy object match (handles nested braces)
    obj_start = text.find("{")
    if obj_start != -1:
        # Walk forward finding the matching close brace
        depth = 0
        for i in range(obj_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[obj_start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    # Strategy 4: first JSON array
    match = _JSON_ARRAY_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON from LLM output: {text[:200]}...")
