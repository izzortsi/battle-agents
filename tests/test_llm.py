"""Tests for the LLM layer: json_utils, ModelRegistry."""

from __future__ import annotations

import pytest

from llm.json_utils import extract_json
from llm.adapter import LLMAdapter, ModelRegistry
from tests.conftest import MockLLM


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


class TestExtractJson:
    def test_pure_json(self):
        result = extract_json('{"action": "attack", "target": "lyra"}')
        assert result == {"action": "attack", "target": "lyra"}

    def test_markdown_fence(self):
        text = 'Here is the response:\n```json\n{"action": "move"}\n```'
        result = extract_json(text)
        assert result == {"action": "move"}

    def test_markdown_fence_no_json_tag(self):
        text = 'Response:\n```\n{"action": "move"}\n```'
        result = extract_json(text)
        assert result == {"action": "move"}

    def test_preamble_text(self):
        text = 'I think the best action is:\n{"action": "defend"}'
        result = extract_json(text)
        assert result == {"action": "defend"}

    def test_nested_objects(self):
        text = '{"outer": {"inner": "value"}}'
        result = extract_json(text)
        assert result == {"outer": {"inner": "value"}}

    def test_json_array(self):
        text = '[1, 2, 3]'
        result = extract_json(text)
        assert result == [1, 2, 3]

    def test_array_with_preamble(self):
        text = 'Here are the questions:\n["q1", "q2", "q3"]'
        result = extract_json(text)
        assert result == ["q1", "q2", "q3"]

    def test_no_json_raises(self):
        with pytest.raises(ValueError, match="Could not extract JSON"):
            extract_json("This is just plain text with no JSON")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            extract_json("")

    def test_whitespace_around_json(self):
        result = extract_json('  \n  {"key": "value"}  \n  ')
        assert result == {"key": "value"}

    def test_complex_nested(self):
        text = '{"questions": ["What is happening?", "Who attacked?"]}'
        result = extract_json(text)
        assert result["questions"] == ["What is happening?", "Who attacked?"]

    def test_json_with_trailing_text(self):
        text = '{"action": "wait"}\nThank you!'
        result = extract_json(text)
        assert result == {"action": "wait"}


# ---------------------------------------------------------------------------
# ModelRegistry
# ---------------------------------------------------------------------------


class TestModelRegistry:
    def test_register_and_get(self):
        reg = ModelRegistry()
        llm = MockLLM()
        reg.register("mock/test", llm)
        assert reg.get("mock/test") is llm

    def test_first_registered_is_default(self):
        reg = ModelRegistry()
        llm = MockLLM()
        reg.register("mock/test", llm)
        assert reg.get() is llm  # default

    def test_set_default(self):
        reg = ModelRegistry()
        llm1 = MockLLM()
        llm2 = MockLLM()
        reg.register("a", llm1)
        reg.register("b", llm2)
        reg.set_default("b")
        assert reg.get() is llm2

    def test_set_default_invalid_key(self):
        reg = ModelRegistry()
        with pytest.raises(KeyError):
            reg.set_default("nonexistent")

    def test_get_no_adapters(self):
        reg = ModelRegistry()
        with pytest.raises(RuntimeError):
            reg.get()

    def test_get_invalid_key(self):
        reg = ModelRegistry()
        reg.register("a", MockLLM())
        with pytest.raises(KeyError):
            reg.get("nonexistent")

    def test_available(self):
        reg = ModelRegistry()
        reg.register("a", MockLLM())
        reg.register("b", MockLLM())
        assert set(reg.available) == {"a", "b"}

    def test_contains(self):
        reg = ModelRegistry()
        reg.register("a", MockLLM())
        assert "a" in reg
        assert "b" not in reg

    def test_len(self):
        reg = ModelRegistry()
        assert len(reg) == 0
        reg.register("a", MockLLM())
        assert len(reg) == 1
