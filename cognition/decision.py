"""Decision module — calls the LLM to select a combat action.

Builds the full prompt context (identity, perceptions, memories, available
actions), sends it to the LLM adapter, parses the JSON response, validates
it against the current game state, and returns a CombatDecision.

Combat supports compound actions: a primary action (move/attack/defend/wait)
PLUS an optional free CHAT that can combine with move, defend, or wait
(but NOT with attack — attacking is exclusive).

Falls back to WAIT if the LLM produces an unparseable or invalid action.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from combat.actions import (
    ActionType,
    CombatAction,
    make_attack,
    make_chat,
    make_defend,
    make_move,
    make_wait,
)
from llm.json_utils import extract_json
from llm.prompts.decision import (
    build_system_prompt,
    build_user_prompt,
    format_visible_enemies,
)
from world.battle_grid import BattleGrid

if TYPE_CHECKING:
    from agent.agent import Agent
    from cognition.memory_stream import MemoryNode
    from llm.adapter import LLMAdapter
    from world.environment import Environment

log = logging.getLogger(__name__)


@dataclass
class CombatDecision:
    """Compound decision for one combat turn.

    primary_action: MOVE, ATTACK, DEFEND, or WAIT (always present).
    chat_action:    Optional free CHAT — can combine with MOVE, DEFEND, or WAIT,
                    but NOT with ATTACK (attacking is exclusive).
    """

    primary_action: CombatAction
    chat_action: CombatAction | None = None


def _gather_context(
    agent: Agent,
    env: Environment,
    perceptions_text: str,
    memories: list[MemoryNode],
) -> dict:
    """Gather all the information needed to build the user prompt.

    Returns a dict of prompt kwargs.
    """
    pos = env.world_state.get_position(agent.agent_id)
    if pos is None:
        return {}  # agent has no position — shouldn't happen

    ax, ay = BattleGrid.parse_tile(pos)

    # Visible enemies with distance and in-range info
    visible_enemies: list[dict] = []
    can_attack: list[str] = []
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
        in_range = dist <= agent.attributes.attack_range
        visible_enemies.append(
            {
                "name": other.identity.name,
                "agent_id": other.agent_id,
                "x": ox,
                "y": oy,
                "distance": dist,
                "hp": other.attributes.hp,
                "max_hp": other.attributes.max_hp,
                "damage_type": other.attributes.damage_type,
                "phys_def": other.attributes.phys_def,
                "mag_def": other.attributes.mag_def,
                "in_attack_range": in_range,
            }
        )
        # Social disposition lookup
        social_dispositions[other.agent_id] = agent.social.get_disposition(
            other.agent_id
        )
        if in_range:
            can_attack.append(f"{other.identity.name} ({other.agent_id})")
        # Can chat with any visible agent (free action, not range-limited)
        can_chat.append(f"{other.identity.name} ({other.agent_id})")

    # Available move tiles (adjacent, passable, unoccupied)
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
        "visible_enemies": visible_enemies,
        "can_attack": can_attack,
        "can_move": can_move,
        "can_chat": can_chat,
        "social_dispositions": social_dispositions,
    }


def _resolve_chat_target(target: str, agent: Agent, env: Environment) -> str | None:
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


def _parse_action(
    raw: dict,
    agent: Agent,
    env: Environment,
    ctx: dict,
) -> CombatDecision:
    """Parse and validate a JSON action response from the LLM.

    Returns a CombatDecision with primary_action and optional chat_action.
    The LLM may provide chat_target/chat_message to combine a free chat with
    the primary action (allowed for move, defend, wait — not attack).
    """
    action_str = raw.get("action", "").lower().strip()
    reasoning = raw.get("reasoning", "")

    primary: CombatAction

    if action_str == "attack":
        target = raw.get("target_agent", "")
        if target and target in env.agents and env.agents[target].is_alive:
            primary = make_attack(agent.agent_id, target, reasoning)
        else:
            # Try to match by name
            resolved = None
            for other in env.alive_agents():
                if other.agent_id == agent.agent_id:
                    continue
                if target and (
                    target.lower() == other.identity.name.lower()
                    or target.lower() == other.agent_id.lower()
                ):
                    resolved = other.agent_id
                    break
            if resolved:
                primary = make_attack(agent.agent_id, resolved, reasoning)
            else:
                log.warning(
                    f"{agent.name}: invalid attack target '{target}', falling back to wait"
                )
                primary = make_wait(agent.agent_id, f"invalid attack target: {target}")

        # Attack is exclusive — no free chat allowed
        return CombatDecision(primary_action=primary, chat_action=None)

    if action_str == "move":
        tile_str = raw.get("target_tile", "")
        if tile_str:
            # Normalise: accept "3_5", "(3, 5)", "3,5", etc.
            tile_str = tile_str.strip().strip("()")
            parts = [p.strip() for p in tile_str.replace("_", ",").split(",")]
            if len(parts) == 2:
                try:
                    tx, ty = int(parts[0]), int(parts[1])
                    tile_key = BattleGrid.tile_key(tx, ty)
                    primary = make_move(agent.agent_id, tile_key, reasoning)
                except ValueError:
                    primary = make_wait(
                        agent.agent_id, f"invalid move tile: {tile_str}"
                    )
            else:
                primary = make_wait(agent.agent_id, f"invalid move tile: {tile_str}")
        else:
            log.warning(
                f"{agent.name}: invalid move tile '{tile_str}', falling back to wait"
            )
            primary = make_wait(agent.agent_id, f"invalid move tile: {tile_str}")

    elif action_str == "defend":
        primary = make_defend(agent.agent_id, reasoning)

    elif action_str == "chat":
        # LLM put chat as primary — treat as wait + chat
        primary = make_wait(agent.agent_id, reasoning)
        # Map old-schema keys to compound keys
        if "chat_target" not in raw and "target_agent" in raw:
            raw["chat_target"] = raw["target_agent"]
        if "chat_message" not in raw and "message" in raw:
            raw["chat_message"] = raw["message"]

    elif action_str == "wait":
        primary = make_wait(agent.agent_id, reasoning)

    else:
        log.warning(
            f"{agent.name}: unrecognised action '{action_str}', falling back to wait"
        )
        primary = make_wait(agent.agent_id, f"unrecognised action: {action_str}")

    # --- Optional free chat (for non-attack primary actions) ---
    chat_action: CombatAction | None = None
    chat_target = raw.get("chat_target", "")
    chat_message = raw.get("chat_message", "")

    if chat_target and chat_message:
        resolved = _resolve_chat_target(chat_target, agent, env)
        if resolved:
            chat_action = make_chat(agent.agent_id, resolved, chat_message, reasoning)
        else:
            log.warning(f"{agent.name}: invalid chat target '{chat_target}'")

    return CombatDecision(primary_action=primary, chat_action=chat_action)


def decide(
    agent: Agent,
    env: Environment,
    perceptions_text: str,
    memories: list[MemoryNode],
    llm: LLMAdapter,
    round_number: int,
    current_plan: str = "",
    chat_allowed: bool = True,
    urgency_text: str = "",
) -> CombatDecision:
    """Use the LLM to select a combat action for this agent.

    1. Build system + user prompts with full context.
    2. Call the LLM.
    3. Parse the JSON response.
    4. Validate and return a CombatDecision (WAIT fallback on any error).

    If chat_allowed is False, the chat option is excluded from the prompt
    and any chat in the response is silently dropped.

    Returns a CombatDecision with primary_action and optional chat_action.
    """
    ctx = _gather_context(agent, env, perceptions_text, memories)
    if not ctx:
        return CombatDecision(primary_action=make_wait(agent.agent_id, "no position"))

    system_prompt = build_system_prompt(agent)

    # Build the user prompt with tile notation for move targets
    can_move_tiles = []
    for tile_label in ctx["can_move"]:
        # Convert "(3, 5)" -> "3_5" for the tile format the resolver expects
        clean = tile_label.strip("()").replace(" ", "")
        parts = clean.split(",")
        if len(parts) == 2:
            can_move_tiles.append(f"({parts[0]}, {parts[1]})")

    user_prompt = build_user_prompt(
        agent=agent,
        round_number=round_number,
        my_x=ctx["ax"],
        my_y=ctx["ay"],
        perceptions_text=perceptions_text,
        memories=memories,
        visible_enemies=ctx["visible_enemies"],
        can_move=can_move_tiles,
        can_attack=ctx["can_attack"],
        can_chat=ctx["can_chat"] if chat_allowed else [],
        current_plan=current_plan,
        social_dispositions=ctx["social_dispositions"],
        urgency_text=urgency_text,
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
        log.debug(f"{agent.name} LLM response: {raw_response[:200]}")
    except Exception as e:
        log.error(f"{agent.name}: LLM call failed: {e}")
        return CombatDecision(
            primary_action=make_wait(agent.agent_id, f"LLM error: {e}")
        )

    # Parse JSON
    try:
        parsed = extract_json(raw_response)
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected dict, got {type(parsed).__name__}")
    except ValueError as e:
        log.error(f"{agent.name}: JSON parse failed: {e}")
        return CombatDecision(
            primary_action=make_wait(agent.agent_id, f"JSON parse error: {e}")
        )

    # Validate and build CombatDecision
    decision = _parse_action(parsed, agent, env, ctx)
    # Strip chat if not allowed (cooldown)
    if not chat_allowed:
        decision = CombatDecision(
            primary_action=decision.primary_action, chat_action=None
        )
    log.info(f"  [{agent.name}] thinks: {parsed.get('reasoning', '?')[:100]}")
    return decision


# ---------------------------------------------------------------------------
# Async variant
# ---------------------------------------------------------------------------


async def async_decide(
    agent: Agent,
    env: Environment,
    perceptions_text: str,
    memories: list[MemoryNode],
    llm: LLMAdapter,
    round_number: int,
    current_plan: str = "",
    chat_allowed: bool = True,
    urgency_text: str = "",
) -> CombatDecision:
    """Async version of decide(). Calls llm.async_complete()."""
    ctx = _gather_context(agent, env, perceptions_text, memories)
    if not ctx:
        return CombatDecision(primary_action=make_wait(agent.agent_id, "no position"))

    system_prompt = build_system_prompt(agent)

    can_move_tiles = []
    for tile_label in ctx["can_move"]:
        clean = tile_label.strip("()").replace(" ", "")
        parts = clean.split(",")
        if len(parts) == 2:
            can_move_tiles.append(f"({parts[0]}, {parts[1]})")

    user_prompt = build_user_prompt(
        agent=agent,
        round_number=round_number,
        my_x=ctx["ax"],
        my_y=ctx["ay"],
        perceptions_text=perceptions_text,
        memories=memories,
        visible_enemies=ctx["visible_enemies"],
        can_move=can_move_tiles,
        can_attack=ctx["can_attack"],
        can_chat=ctx["can_chat"] if chat_allowed else [],
        current_plan=current_plan,
        social_dispositions=ctx["social_dispositions"],
        urgency_text=urgency_text,
    )

    try:
        raw_response = await llm.async_complete(
            system=system_prompt,
            user=user_prompt,
            max_tokens=256,
            temperature=0.7,
            response_format="json",
        )
        log.debug(f"{agent.name} LLM response: {raw_response[:200]}")
    except Exception as e:
        log.error(f"{agent.name}: LLM call failed: {e}")
        return CombatDecision(
            primary_action=make_wait(agent.agent_id, f"LLM error: {e}")
        )

    try:
        parsed = extract_json(raw_response)
        if not isinstance(parsed, dict):
            raise ValueError(f"Expected dict, got {type(parsed).__name__}")
    except ValueError as e:
        log.error(f"{agent.name}: JSON parse failed: {e}")
        return CombatDecision(
            primary_action=make_wait(agent.agent_id, f"JSON parse error: {e}")
        )

    decision = _parse_action(parsed, agent, env, ctx)
    if not chat_allowed:
        decision = CombatDecision(
            primary_action=decision.primary_action, chat_action=None
        )
    log.info(f"  [{agent.name}] thinks: {parsed.get('reasoning', '?')[:100]}")
    return decision
