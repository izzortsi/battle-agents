"""Reflection — importance-triggered higher-level synthesis.

Implements the Park et al. reflection mechanism:
  When importance_accumulator >= threshold (default 50):
  1. Gather the 100 most recent memories
  2. LLM asks "what are 3 high-level questions?"
  3. For each question, retrieve relevant memories
  4. LLM generates insights citing evidence by statement number
  5. Store as MemoryNode(depth=1, type=REFLECTION)
  6. Reset importance_accumulator

Reflections participate in future retrievals, creating recursive
reflection trees where higher-level abstractions build on lower ones.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cognition.memory_stream import MemoryStream, MemoryType
from cognition.retrieval import retrieve
from llm.json_utils import extract_json
from llm.prompts.reflection import build_insight_prompts, build_question_prompts

if TYPE_CHECKING:
    from llm.adapter import LLMAdapter

log = logging.getLogger(__name__)


def reflect(
    agent_name: str,
    combat_class: str,
    memory: MemoryStream,
    llm: LLMAdapter,
    current_turn: int,
    threshold: float = 50.0,
) -> list[int]:
    """Run the reflection process if importance threshold is met.

    Returns list of newly created reflection node IDs (empty if
    threshold not met or reflection fails).
    """
    if memory.importance_accumulator < threshold:
        return []

    log.info(
        f"  [{agent_name}] Reflecting... "
        f"(importance: {memory.importance_accumulator:.0f} >= {threshold:.0f})"
    )

    # 1. Gather the 100 most recent memories
    recent = memory.get_recent(100)
    if len(recent) < 3:
        log.debug(f"  [{agent_name}] Too few memories to reflect ({len(recent)})")
        return []

    # 2. Generate 3 high-level questions
    questions = _generate_questions(agent_name, combat_class, recent, llm)
    if not questions:
        log.warning(f"  [{agent_name}] Question generation failed")
        return []

    log.debug(f"  [{agent_name}] Reflection questions: {questions}")

    # 3-4. For each question, retrieve relevant memories and generate insight
    new_ids: list[int] = []
    for question in questions:
        # Retrieve memories relevant to this question
        relevant = retrieve(
            memory=memory,
            query=question,
            current_turn=current_turn,
            top_k=10,
        )

        if not relevant:
            continue

        # Generate insight
        insight, evidence_ids = _generate_insight(
            agent_name, combat_class, question, relevant, llm
        )
        if not insight:
            continue

        # 5. Store as reflection node
        node = memory.add(
            turn=current_turn,
            memory_type=MemoryType.REFLECTION,
            description=insight,
            poignancy=8,  # reflections are inherently important
            depth=1,
            subject=agent_name,
            predicate="reflected",
            object_=question[:50],
            evidence_ids=evidence_ids,
        )
        new_ids.append(node.node_id)
        log.info(f"  [{agent_name}] Reflection: {insight}")

    # 6. Reset importance accumulator
    memory.reset_importance()

    log.info(f"  [{agent_name}] Reflection complete: {len(new_ids)} insights generated")
    return new_ids


def _generate_questions(
    agent_name: str,
    combat_class: str,
    recent_memories: list,
    llm: LLMAdapter,
) -> list[str]:
    """Stage 1: Generate 3 high-level questions from recent memories."""
    system, user = build_question_prompts(agent_name, combat_class, recent_memories)

    try:
        raw = llm.complete(
            system=system,
            user=user,
            max_tokens=256,
            temperature=0.6,
            response_format="json",
        )
        parsed = extract_json(raw)
        if isinstance(parsed, dict) and "questions" in parsed:
            questions = parsed["questions"]
            if isinstance(questions, list):
                return [str(q) for q in questions[:3]]
    except Exception as e:
        log.warning(f"  [{agent_name}] Question generation LLM error: {e}")

    return []


def _generate_insight(
    agent_name: str,
    combat_class: str,
    question: str,
    relevant_memories: list,
    llm: LLMAdapter,
) -> tuple[str, list[int]]:
    """Stage 2: Generate an insight for a question, citing evidence.

    Returns (insight_text, list_of_evidence_node_ids).
    """
    system, user = build_insight_prompts(
        agent_name, combat_class, question, relevant_memories
    )

    try:
        raw = llm.complete(
            system=system,
            user=user,
            max_tokens=256,
            temperature=0.5,
            response_format="json",
        )
        parsed = extract_json(raw)
        if isinstance(parsed, dict) and "insight" in parsed:
            insight = str(parsed["insight"])
            # Map statement numbers back to node IDs
            evidence_nums = parsed.get("evidence", [])
            evidence_ids = []
            for num in evidence_nums:
                try:
                    idx = int(num) - 1  # 1-indexed in prompt
                    if 0 <= idx < len(relevant_memories):
                        evidence_ids.append(relevant_memories[idx].node_id)
                except (ValueError, TypeError):
                    continue
            return insight, evidence_ids
    except Exception as e:
        log.warning(f"  [{agent_name}] Insight generation LLM error: {e}")

    return "", []
