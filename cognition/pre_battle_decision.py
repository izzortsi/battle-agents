"""Pre-battle decision module — social-phase compound action selection via LLM.

During the pre-battle phase agents choose a compound action each tick:
  - PRIMARY: MOVE or WAIT
  - OPTIONAL FREE CHAT: target + message (no action cost)

This module mirrors cognition/decision.py but with a social-only action
space and compound output.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from combat.actions import (
    CombatAction,
    make_chat,
    make_move,
    make_wait,
)
from llm.json_utils import extract_json
from llm.prompts.pre_battle_decision import (
    build_pre_battle_system_prompt,
    build_pre_battle_user_prompt,
)
from world.battle_grid import BattleGrid

if TYPE_CHECKING:
    from agent.agent import Agent
    from cognition.memory_stream import MemoryNode
    from llm.adapter import LLMAdapter
    from world.environment import Environment

log = logging.getLogger(__name__)


@dataclass
class PreBattleDecision:
    """Compound decision for one pre-battle tick.

    primary_action: MOVE or WAIT (always present).
    chat_action:    CHAT action (optional — free, can combine with primary).
    """

    primary_action: CombatAction
    chat_action: CombatAction | None = None


def _gather_pre_battle_context(
    agent: Agent,
    env: Environment,
) -> dict:
    """Gather context for a pre-battle social decision.

    Similar to decision._gather_context but simpler — no attack targets,
    and we include combat_class for each visible agent.
    """
    pos = env.world_state.get_position(agent.agent_id)
    if pos is None:
        return {}

    ax, ay = BattleGrid.parse_tile(pos)

    visible_agents: list[dict] = []
    can_chat: list[str] = []
    social_dispositions: dict[str, float] = {}

    for other in env.alive_agents():
        if other.agent_id == agent.agent_id:
            continue
        other_pos = env.world_state.get_position(other.agent_id)
        if other_pos is None:
            continue
        ox, oy = BattleGrid.parse_tile(other_pos)
        dist = BattleGrid.manhattan(ax, ay, ox, oy)

        # Only include agents within perception radius
        if dist > env.perception_engine.perception_radius:
            continue

        visible_agents.append(
            {
                "name": other.identity.name,
                "agent_id": other.agent_id,
                "x": ox,
                "y": oy,
                "distance": dist,
                "combat_class": other.identity.combat_class,
            }
        )
        social_dispositions[other.agent_id] = agent.social.get_disposition(
            other.agent_id
        )
        # In pre-battle, can chat with anyone visible (no range restriction)
        can_chat.append(f"{other.identity.name} ({other.agent_id})")

    # Available move tiles
    can_move: list[str] = []
    for tx, ty in env.grid.adjacent_tiles(ax, ay):
        tile_key = BattleGrid.tile_key(tx, ty)
        occupants = env.world_state.agents_at(tile_key)
        living_occ = [
            o
            for o in occupants
            if o != agent.agent_id and env.agents.get(o) and env.agents[o].is_alive
        ]
        if not living_occ:
            can_move.append(f"({tx}, {ty})")

    return {
        "ax": ax,
        "ay": ay,
        "visible_agents": visible_agents,
        "can_move": can_move,
        "can_chat": can_chat,
        "social_dispositions": social_dispositions,
    }


def _resolve_target(target: str, agent: Agent, env: Environment) -> str | None:
    """Resolve a chat target string to an agent_id, or None if invalid."""
    if target and target in env.agents and env.agents[target].is_alive:
        return target
    for other in env.alive_agents():
        if other.agent_id == agent.agent_id:
            continue
        if target and (
            target.lower() == other.identity.name.lower()
            or target.lower() == other.agent_id.lower()
        ):
            return other.agent_id
    return None


def _parse_pre_battle_decision(
    raw: dict,
    agent: Agent,
    env: Environment,
    ctx: dict,
) -> PreBattleDecision:
    """Parse a compound pre-battle JSON response.

    Expected keys:
      action:       "move" or "wait" (primary)
      target_tile:  tile for move
      chat_target:  agent_id for optional free chat
      chat_message: message for optional free chat
    """
    reasoning = raw.get("reasoning", "")

    # --- Primary action ---
    action_str = raw.get("action", "").lower().strip()

    if action_str == "move":
        tile_str = raw.get("target_tile", "")
        if tile_str:
            tile_str = tile_str.strip().strip("()")
            parts = [p.strip() for p in tile_str.replace("_", ",").split(",")]
            if len(parts) == 2:
                try:
                    tx, ty = int(parts[0]), int(parts[1])
                    tile_key = BattleGrid.tile_key(tx, ty)
                    primary = make_move(agent.agent_id, tile_key, reasoning)
                except ValueError:
                    log.warning(
                        f"{agent.name}: invalid pre-battle move tile '{tile_str}'"
                    )
                    primary = make_wait(agent.agent_id, f"invalid tile: {tile_str}")
            else:
                primary = make_wait(agent.agent_id, f"bad tile format: {tile_str}")
        else:
            primary = make_wait(agent.agent_id, "move with no tile")
    elif action_str in ("attack", "defend"):
        log.warning(
            f"{agent.name}: tried to {action_str} during pre-battle, "
            "falling back to wait"
        )
        primary = make_wait(agent.agent_id, f"'{action_str}' not allowed pre-battle")
    elif action_str == "chat":
        # LLM put chat as primary — treat as wait + chat
        primary = make_wait(agent.agent_id, reasoning)
        # Fall through to chat parsing below; if the LLM used the old schema
        # keys (target_agent / message), map them to chat_target / chat_message
        if "chat_target" not in raw and "target_agent" in raw:
            raw["chat_target"] = raw["target_agent"]
        if "chat_message" not in raw and "message" in raw:
            raw["chat_message"] = raw["message"]
    else:
        # Default: wait
        primary = make_wait(agent.agent_id, reasoning)

    # --- Optional free chat ---
    chat_action: CombatAction | None = None
    chat_target = raw.get("chat_target", "")
    chat_message = raw.get("chat_message", "")

    if chat_target and chat_message:
        resolved = _resolve_target(chat_target, agent, env)
        if resolved:
            chat_action = make_chat(agent.agent_id, resolved, chat_message, reasoning)
        else:
            log.warning(f"{agent.name}: invalid pre-battle chat target '{chat_target}'")

    return PreBattleDecision(primary_action=primary, chat_action=chat_action)


def decide_pre_battle(
    agent: Agent,
    env: Environment,
    perceptions_text: str,
    memories: list[MemoryNode],
    llm: LLMAdapter,
    tick_number: int,
    total_ticks: int,
    current_plan: str = "",
) -> PreBattleDecision:
    """Use the LLM to select a compound pre-battle action.

    Returns a PreBattleDecision with:
      - primary_action: MOVE or WAIT
      - chat_action:    optional free CHAT (can combine with primary)
    """
    ctx = _gather_pre_battle_context(agent, env)
    if not ctx:
        return PreBattleDecision(
            primary_action=make_wait(agent.agent_id, "no position")
        )

    system_prompt = build_pre_battle_system_prompt(agent)

    # Build move tile labels
    can_move_tiles = []
    for tile_label in ctx["can_move"]:
        clean = tile_label.strip("()").replace(" ", "")
        parts = clean.split(",")
        if len(parts) == 2:
            can_move_tiles.append(f"({parts[0]}, {parts[1]})")

    user_prompt = build_pre_battle_user_prompt(
        agent=agent,
        tick_number=tick_number,
        total_ticks=total_ticks,
        my_x=ctx["ax"],
        my_y=ctx["ay"],
        perceptions_text=perceptions_text,
        memories=memories,
        visible_agents=ctx["visible_agents"],
        can_move=can_move_tiles,
        can_chat=ctx["can_chat"],
        current_plan=current_plan,
        social_dispositions=ctx["social_dispositions"],
    )

    # Call LLM
    try:
        raw_response = llm.complete(
            system=system_prompt,
            user=user_prompt,
            max_tokens=256,
            temperature=0.7,
            response_format="json",
        )
        log.debug(f"{agent.name} pre-battle LLM response: {raw_response[:200]}")
    except Exception as e:
        log.error(f"{agent.name}: pre-battle LLM call failed: {e}")
        return PreBattleDecision(
            primary_action=make_wait(agent.agent_id, f"LLM error: {e}")
        )

    # Parse JSON
    try:
        parsed = extract_json(raw_response)
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected dict, got {type(parsed).__name__}")
    except ValueError as e:
        log.error(f"{agent.name}: pre-battle JSON parse failed: {e}")
        return PreBattleDecision(
            primary_action=make_wait(agent.agent_id, f"JSON parse error: {e}")
        )

    # Validate and build compound decision
    decision = _parse_pre_battle_decision(parsed, agent, env, ctx)
    log.info(f"  [{agent.name}] thinks: {parsed.get('reasoning', '?')[:100]}")
    return decision


# ---------------------------------------------------------------------------
# Async variant
# ---------------------------------------------------------------------------


async def async_decide_pre_battle(
    agent: Agent,
    env: Environment,
    perceptions_text: str,
    memories: list[MemoryNode],
    llm: LLMAdapter,
    tick_number: int,
    total_ticks: int,
    current_plan: str = "",
) -> PreBattleDecision:
    """Async version of decide_pre_battle(). Calls llm.async_complete()."""
    ctx = _gather_pre_battle_context(agent, env)
    if not ctx:
        return PreBattleDecision(
            primary_action=make_wait(agent.agent_id, "no position")
        )

    system_prompt = build_pre_battle_system_prompt(agent)

    can_move_tiles = []
    for tile_label in ctx["can_move"]:
        clean = tile_label.strip("()").replace(" ", "")
        parts = clean.split(",")
        if len(parts) == 2:
            can_move_tiles.append(f"({parts[0]}, {parts[1]})")

    user_prompt = build_pre_battle_user_prompt(
        agent=agent,
        tick_number=tick_number,
        total_ticks=total_ticks,
        my_x=ctx["ax"],
        my_y=ctx["ay"],
        perceptions_text=perceptions_text,
        memories=memories,
        visible_agents=ctx["visible_agents"],
        can_move=can_move_tiles,
        can_chat=ctx["can_chat"],
        current_plan=current_plan,
        social_dispositions=ctx["social_dispositions"],
    )

    try:
        raw_response = await llm.async_complete(
            system=system_prompt,
            user=user_prompt,
            max_tokens=256,
            temperature=0.7,
            response_format="json",
        )
        log.debug(f"{agent.name} pre-battle LLM response: {raw_response[:200]}")
    except Exception as e:
        log.error(f"{agent.name}: pre-battle LLM call failed: {e}")
        return PreBattleDecision(
            primary_action=make_wait(agent.agent_id, f"LLM error: {e}")
        )

    try:
        parsed = extract_json(raw_response)
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected dict, got {type(parsed).__name__}")
    except ValueError as e:
        log.error(f"{agent.name}: pre-battle JSON parse failed: {e}")
        return PreBattleDecision(
            primary_action=make_wait(agent.agent_id, f"JSON parse error: {e}")
        )

    decision = _parse_pre_battle_decision(parsed, agent, env, ctx)
    log.info(f"  [{agent.name}] thinks: {parsed.get('reasoning', '?')[:100]}")
    return decision
