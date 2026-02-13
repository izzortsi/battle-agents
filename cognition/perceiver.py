"""Perceiver — converts Observations from the perception engine into MemoryNodes.

Each Observation becomes an OBSERVATION-type MemoryNode with a heuristic
poignancy score (importance) based on the category and details.
"""

from __future__ import annotations

from cognition.memory_stream import MemoryStream, MemoryType
from world.perception_engine import Observation


# -- Poignancy heuristics (before we have LLM scoring) ---------------------

_CATEGORY_BASE_POIGNANCY: dict[str, int] = {
    "agent_action": 5,
    "agent_position": 2,
    "agent_status": 3,
    "event": 6,
}

_ACTION_TYPE_BONUS: dict[str, int] = {
    "attack": 3,
    "ability": 3,
    "chat": 2,
    "defend": 1,
    "move": 0,
    "wait": 0,
}


def _estimate_poignancy(obs: Observation) -> int:
    """Heuristic poignancy score for an observation (1–10 scale).

    Will be replaced by LLM-scored poignancy in a later phase.
    """
    base = _CATEGORY_BASE_POIGNANCY.get(obs.category, 3)

    # Bonus for combat actions
    action_type = obs.details.get("action_type", "")
    base += _ACTION_TYPE_BONUS.get(action_type, 0)

    # Bonus if someone is low HP
    hp = obs.details.get("hp")
    max_hp = obs.details.get("max_hp")
    if hp is not None and max_hp is not None and max_hp > 0:
        hp_ratio = hp / max_hp
        if hp_ratio <= 0.25:
            base += 3  # critically wounded — very important
        elif hp_ratio <= 0.50:
            base += 1

    # Bonus for kills
    if obs.details.get("killed"):
        base += 4

    return min(max(base, 1), 10)


def _extract_spo(obs: Observation) -> tuple[str, str, str]:
    """Extract a rough subject-predicate-object triple from an observation."""
    subject = obs.subject or ""
    details = obs.details

    if obs.category == "agent_action":
        action_type = details.get("action_type", "acted")
        target = details.get("target_agent", details.get("target_tile", ""))
        return subject, action_type, str(target)

    if obs.category == "agent_position":
        tile = details.get("tile", "")
        return subject, "occupies", str(tile)

    if obs.category == "agent_status":
        statuses = details.get("statuses", [])
        return subject, "has_status", ", ".join(statuses)

    return subject, "observed", ""


def perceive_to_memory(
    observations: list[Observation],
    memory: MemoryStream,
    current_turn: int,
) -> list[int]:
    """Convert a batch of Observations into MemoryNodes and store them.

    Returns the list of new node IDs.
    """
    new_ids: list[int] = []
    for obs in observations:
        poignancy = _estimate_poignancy(obs)
        s, p, o = _extract_spo(obs)
        node = memory.add(
            turn=current_turn,
            memory_type=MemoryType.OBSERVATION,
            description=obs.description,
            poignancy=poignancy,
            depth=0,
            subject=s,
            predicate=p,
            object_=o,
        )
        new_ids.append(node.node_id)
    return new_ids
