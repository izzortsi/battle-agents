"""Reflection prompt templates — builds LLM prompts for reflective synthesis.

Used by cognition/reflection.py when importance_accumulator crosses the
threshold.  Two-stage process:
  1. Question generation — given recent memories, ask 3 high-level questions
  2. Insight generation — for each question, generate an insight citing evidence
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cognition.memory_stream import MemoryNode


# -- Stage 1: Question generation -------------------------------------------

QUESTION_SYSTEM = """\
You are analyzing the recent experiences of a combat agent named {name} \
({combat_class}). Your job is to identify the most important high-level \
questions that can be answered from these observations.

Respond with a JSON object:
{{
  "questions": [
    "<question 1>",
    "<question 2>",
    "<question 3>"
  ]
}}

Generate exactly 3 questions. Focus on:
- Strategic patterns (who is the biggest threat? who might be an ally?)
- Tactical insights (what worked? what didn't? what should change?)
- Social dynamics (who is cooperating? who is betraying? who is vulnerable?)\
"""


QUESTION_USER = """\
Here are {name}'s recent experiences (most recent first):

{statements}

Given only the statements above, what are 3 salient high-level questions \
we can answer about {name}'s situation and relationships?
JSON only.\
"""


# -- Stage 2: Insight generation ---------------------------------------------

INSIGHT_SYSTEM = """\
You are synthesizing insights from the experiences of {name}, a {combat_class} \
in tactical combat. Generate a concise insight that answers the given question, \
citing evidence by statement number.

Respond with a JSON object:
{{
  "insight": "<1-2 sentence insight, in third person>",
  "evidence": [<list of statement numbers that support this insight>]
}}

The insight should be a high-level conclusion, not just a restatement of facts.\
"""


INSIGHT_USER = """\
Question: {question}

Relevant statements about {name}:
{statements}

What insight can you infer from these statements? Cite evidence by statement number.
JSON only.\
"""


# -- Builder functions -------------------------------------------------------


def build_question_prompts(
    agent_name: str,
    combat_class: str,
    recent_memories: list[MemoryNode],
) -> tuple[str, str]:
    """Build system + user prompts for question generation."""
    statements = _format_numbered_statements(recent_memories)
    system = QUESTION_SYSTEM.format(name=agent_name, combat_class=combat_class)
    user = QUESTION_USER.format(name=agent_name, statements=statements)
    return system, user


def build_insight_prompts(
    agent_name: str,
    combat_class: str,
    question: str,
    relevant_memories: list[MemoryNode],
) -> tuple[str, str]:
    """Build system + user prompts for insight generation."""
    statements = _format_numbered_statements(relevant_memories)
    system = INSIGHT_SYSTEM.format(name=agent_name, combat_class=combat_class)
    user = INSIGHT_USER.format(
        question=question,
        name=agent_name,
        statements=statements,
    )
    return system, user


def _format_numbered_statements(memories: list[MemoryNode]) -> str:
    """Format memories as numbered statements for the prompt."""
    if not memories:
        return "  (no statements)"
    lines = []
    for i, m in enumerate(memories, 1):
        lines.append(f"  {i}. [turn {m.turn_created}] {m.description}")
    return "\n".join(lines)
