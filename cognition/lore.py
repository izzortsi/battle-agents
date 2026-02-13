"""Lore generation — LLM-powered world context for the combat arena.

Generates world lore before battle starts. The lore is:
1. Broadcast to the frontend for display
2. Injected as turn-0 memories for all agents
3. Included in decision system prompts as world context
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from llm.json_utils import extract_json
from llm.prompts.lore import build_lore_prompts

if TYPE_CHECKING:
    from llm.adapter import LLMAdapter

log = logging.getLogger(__name__)


@dataclass
class LoreContext:
    """Generated world lore for a battle."""

    world_description: str = ""
    key_facts: list[str] = field(default_factory=list)
    character_connections: list[dict] = field(default_factory=list)
    raw_text: str = ""  # Formatted text for injection into prompts

    def to_prompt_text(self) -> str:
        """Format the lore as text suitable for system prompt injection."""
        if self.raw_text:
            return self.raw_text

        parts = []
        if self.world_description:
            parts.append(self.world_description)
        if self.key_facts:
            parts.append("Key facts:")
            for fact in self.key_facts:
                parts.append(f"  - {fact}")
        if self.character_connections:
            parts.append("Character connections:")
            for conn in self.character_connections:
                names = ", ".join(conn.get("characters", []))
                desc = conn.get("connection", "")
                parts.append(f"  - {names}: {desc}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        """Serialize for WebSocket broadcast."""
        return {
            "world_description": self.world_description,
            "key_facts": self.key_facts,
            "character_connections": self.character_connections,
        }


def generate_lore(
    characters: list[dict],
    llm: LLMAdapter,
    user_prompt: str = "",
) -> LoreContext:
    """Generate world lore using the LLM.

    Args:
        characters: List of character summary dicts (name, combat_class, backstory, personality_traits).
        llm: The LLM adapter to use for generation.
        user_prompt: Optional user-provided setting/theme prompt.

    Returns:
        LoreContext with generated lore.
    """
    system, user = build_lore_prompts(characters, user_prompt)

    try:
        raw = llm.complete(
            system=system,
            user=user,
            max_tokens=512,
            temperature=0.8,
            response_format="json",
        )
        log.debug(f"Lore LLM response: {raw[:200]}")
    except Exception as e:
        log.error(f"Lore generation failed: {e}")
        return LoreContext()

    try:
        data = extract_json(raw)
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")
    except ValueError as e:
        log.error(f"Lore JSON parse failed: {e}")
        # Fall back to raw text
        return LoreContext(raw_text=raw.strip())

    lore = LoreContext(
        world_description=data.get("world_description", ""),
        key_facts=data.get("key_facts", []),
        character_connections=data.get("character_connections", []),
    )
    lore.raw_text = lore.to_prompt_text()

    log.info(f"Generated world lore ({len(lore.raw_text)} chars)")
    return lore


def inject_lore_memories(
    lore: LoreContext,
    agents: list,
    cognitive_loop,
) -> None:
    """Inject lore as turn-0 memories for all agents.

    Creates observation memories so agents "know" the world context.
    """
    from cognition.memory_stream import MemoryType

    if not lore.world_description:
        return

    for agent in agents:
        state = cognitive_loop.get_state(agent.agent_id)
        if state is None:
            continue

        # Inject world description as a high-importance memory
        state.memory.add(
            turn=0,
            memory_type=MemoryType.OBSERVATION,
            description=f"World lore: {lore.world_description}",
            poignancy=8,
            depth=0,
            subject="world",
            predicate="is",
            object_=lore.world_description[:100],
        )

        # Inject relevant character connections
        for conn in lore.character_connections:
            names = conn.get("characters", [])
            if agent.identity.name in names or agent.name in names:
                state.memory.add(
                    turn=0,
                    memory_type=MemoryType.OBSERVATION,
                    description=f"Known connection: {conn.get('connection', '')}",
                    poignancy=7,
                    depth=0,
                    subject=agent.identity.name,
                    predicate="knows",
                    object_=conn.get("connection", "")[:100],
                )

    log.info(f"Injected lore memories for {len(agents)} agents")
