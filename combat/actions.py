"""Combat action types and data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ActionType(str, Enum):
    MOVE = "move"
    ATTACK = "attack"
    DEFEND = "defend"
    ABILITY = "ability"
    CHAT = "chat"
    WAIT = "wait"


@dataclass
class CombatAction:
    """A single action emitted by an agent."""

    agent_id: str
    action_type: ActionType
    target_tile: Optional[str] = None  # for MOVE
    target_agent: Optional[str] = None  # for ATTACK, ABILITY, CHAT
    ability_name: Optional[str] = None  # for ABILITY
    message: Optional[str] = None  # for CHAT
    reasoning: str = ""  # agent's internal reasoning (for logging/debug)

    def __str__(self) -> str:
        parts = [f"{self.agent_id}: {self.action_type.value}"]
        if self.target_tile:
            parts.append(f"-> tile {self.target_tile}")
        if self.target_agent:
            parts.append(f"-> {self.target_agent}")
        if self.ability_name:
            parts.append(f"({self.ability_name})")
        if self.message:
            parts.append(f'"{self.message[:50]}"')
        return " ".join(parts)


def make_move(agent_id: str, tile: str, reasoning: str = "") -> CombatAction:
    return CombatAction(
        agent_id=agent_id,
        action_type=ActionType.MOVE,
        target_tile=tile,
        reasoning=reasoning,
    )


def make_attack(agent_id: str, target: str, reasoning: str = "") -> CombatAction:
    return CombatAction(
        agent_id=agent_id,
        action_type=ActionType.ATTACK,
        target_agent=target,
        reasoning=reasoning,
    )


def make_defend(agent_id: str, reasoning: str = "") -> CombatAction:
    return CombatAction(
        agent_id=agent_id, action_type=ActionType.DEFEND, reasoning=reasoning
    )


def make_chat(
    agent_id: str, target: str, message: str, reasoning: str = ""
) -> CombatAction:
    return CombatAction(
        agent_id=agent_id,
        action_type=ActionType.CHAT,
        target_agent=target,
        message=message,
        reasoning=reasoning,
    )


def make_wait(agent_id: str, reasoning: str = "") -> CombatAction:
    return CombatAction(
        agent_id=agent_id, action_type=ActionType.WAIT, reasoning=reasoning
    )


def make_ability(
    agent_id: str,
    target: str | None,
    ability_name: str,
    reasoning: str = "",
) -> CombatAction:
    """Create an ABILITY action.  *target* is None for self-targeting abilities."""
    return CombatAction(
        agent_id=agent_id,
        action_type=ActionType.ABILITY,
        target_agent=target,
        ability_name=ability_name,
        reasoning=reasoning,
    )
