"""Decision module — calls the LLM to select a combat action.

Builds the full prompt context (identity, perceptions, memories, available
actions), sends it to the LLM adapter, parses the JSON response, validates
it against the current game state, and returns a CombatDecision.

Combat supports compound actions: an optional MOVE prefix, a primary action
(attack/defend/ability/wait), and an optional free CHAT.  Move can combine
with any primary action — the agent moves first, then acts from the new
position.

Falls back to WAIT if the LLM produces an unparseable or invalid action.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from combat.actions import (
    ActionType,
    CombatAction,
    make_ability,
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

    move_action:    Optional free MOVE (before or after the primary action).
    primary_action: ATTACK, DEFEND, ABILITY, or WAIT (always present).
    chat_action:    Optional free CHAT — can combine with any primary action.
    move_after:     If True, the move is resolved *after* the primary action.
    """

    primary_action: CombatAction
    move_action: CombatAction | None = None
    chat_action: CombatAction | None = None
    move_after: bool = False


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

        # Compute which skills can reach this target
        reachable_by: list[str] = []
        if in_range:
            reachable_by.append("attack")
        for ab in agent.attributes.get_ready_abilities():
            ab_range = ab.get("range", 1)
            if dist <= ab_range:
                reachable_by.append(ab["name"])

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
                "reachable_by": reachable_by,
            }
        )
        # Social disposition lookup
        social_dispositions[other.agent_id] = agent.social.get_disposition(
            other.agent_id
        )
        if in_range:
            can_attack.append(f"{other.identity.name} ({other.agent_id})")
        # Can chat within speak radius (yelling distance in combat)
        if dist <= env.chat_speak_radius:
            can_chat.append(f"{other.identity.name} ({other.agent_id})")

    # Alliance statuses (formal mutual labels from the resolver)
    alliance_statuses = env.get_all_alliance_statuses(agent.agent_id)

    # Available move tiles (within move range, passable, unoccupied)
    move_range = agent.attributes.move_range
    can_move: list[str] = []
    for tx, ty in env.grid.tiles_in_range(ax, ay, move_range):
        if tx == ax and ty == ay:
            continue  # skip current position
        tile_key = BattleGrid.tile_key(tx, ty)
        occupants = env.world_state.agents_at(tile_key)
        living_occ = [
            o
            for o in occupants
            if o != agent.agent_id and env.agents.get(o) and env.agents[o].is_alive
        ]
        if not living_occ:
            can_move.append(f"({tx}, {ty})")

    # Eliminated combatants (from the death log)
    eliminated = list(env.death_log)  # shallow copy

    return {
        "ax": ax,
        "ay": ay,
        "visible_enemies": visible_enemies,
        "can_attack": can_attack,
        "can_move": can_move,
        "can_chat": can_chat,
        "can_ability": _compute_can_ability(agent, env, ax, ay),
        "social_dispositions": social_dispositions,
        "alliance_statuses": alliance_statuses,
        "eliminated": eliminated,
    }


def _compute_can_ability(
    agent: Agent,
    env: Environment,
    ax: int,
    ay: int,
) -> list[str]:
    """Compute which abilities the agent can use and against whom.

    Returns a list of display strings like:
      "Berserker Slash -> Kael (kael), Lyra (lyra)"
      "Divine Light -> self"
      "Mending Touch -> [ALLY] Kael (kael)"
    """
    ready = agent.attributes.get_ready_abilities()
    if not ready:
        return []

    result: list[str] = []
    for ability in ready:
        ab_range = ability.get("range", 1)
        effects = ability.get("effects", [])

        # Determine if self-targeting
        is_self = (
            all(e.get("target", "enemy") == "self" for e in effects)
            if effects
            else False
        )
        if ability.get("damage", 0) == 0 and is_self:
            is_self = True

        # Determine if ally-targeting
        is_ally_targeting = False
        if effects and not is_self:
            has_ally_effects = any(e.get("target") == "ally" for e in effects)
            if has_ally_effects and ability.get("damage", 0) == 0:
                is_ally_targeting = True

        if is_self:
            result.append(f"{ability['name']} -> self")
        elif is_ally_targeting:
            # Ally-targeting: list self + all agents in range (allies get [ALLY] tag)
            allies_in_range: list[str] = ["self"]
            for other in env.alive_agents():
                if other.agent_id == agent.agent_id:
                    continue
                other_pos = env.world_state.get_position(other.agent_id)
                if other_pos is None:
                    continue
                ox, oy = BattleGrid.parse_tile(other_pos)
                dist = BattleGrid.manhattan(ax, ay, ox, oy)
                if dist <= ab_range:
                    allies_in_range.append(
                        f"[ALLY] {other.identity.name} ({other.agent_id})"
                    )
            if allies_in_range:
                result.append(f"{ability['name']} -> {', '.join(allies_in_range)}")
        else:
            # Find valid targets in range
            targets_in_range: list[str] = []
            for other in env.alive_agents():
                if other.agent_id == agent.agent_id:
                    continue
                other_pos = env.world_state.get_position(other.agent_id)
                if other_pos is None:
                    continue
                ox, oy = BattleGrid.parse_tile(other_pos)
                dist = BattleGrid.manhattan(ax, ay, ox, oy)
                if dist <= ab_range:
                    targets_in_range.append(f"{other.identity.name} ({other.agent_id})")
            if targets_in_range:
                result.append(f"{ability['name']} -> {', '.join(targets_in_range)}")
            # If no targets in range, don't list this ability

    return result


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


def _parse_move(raw: dict, agent: Agent) -> CombatAction | None:
    """Extract an optional move action from target_tile.  Returns None if absent."""
    tile_val = raw.get("target_tile", "")
    if not tile_val:
        return None
    # LLMs sometimes put an agent id or "null"/"none" in target_tile
    if isinstance(tile_val, str) and tile_val.strip().lower() in ("null", "none", ""):
        return None
    # LLMs sometimes return a list like [3, 5] instead of "3,5"
    if isinstance(tile_val, (list, tuple)):
        if len(tile_val) == 2:
            try:
                tx, ty = int(tile_val[0]), int(tile_val[1])
                tile_key = BattleGrid.tile_key(tx, ty)
                return make_move(agent.agent_id, tile_key, raw.get("reasoning", ""))
            except (ValueError, TypeError):
                pass
        log.warning(f"{agent.name}: invalid move tile '{tile_val}', skipping move")
        return None
    # Normalise strings: accept "3_5", "(3, 5)", "3,5", etc.
    tile_str = str(tile_val).strip().strip("()")
    parts = [p.strip() for p in tile_str.replace("_", ",").split(",")]
    if len(parts) == 2:
        try:
            tx, ty = int(parts[0]), int(parts[1])
            tile_key = BattleGrid.tile_key(tx, ty)
            return make_move(agent.agent_id, tile_key, raw.get("reasoning", ""))
        except ValueError:
            log.warning(f"{agent.name}: invalid move tile '{tile_str}', skipping move")
            return None
    log.warning(f"{agent.name}: invalid move tile '{tile_str}', skipping move")
    return None


def _parse_action(
    raw: dict,
    agent: Agent,
    env: Environment,
    ctx: dict,
) -> CombatDecision:
    """Parse and validate a JSON action response from the LLM.

    Returns a CombatDecision with optional move_action, primary_action, and
    optional chat_action.  Move is extracted from target_tile on any action
    type — the agent moves first, then acts from the new position.
    """
    action_str = raw.get("action", "").lower().strip()
    reasoning = raw.get("reasoning", "")

    # --- Extract optional move prefix from target_tile ---
    move_action = _parse_move(raw, agent)

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

    elif action_str == "ability":
        ability_name = raw.get("ability_name", "")
        if not ability_name:
            log.warning(
                f"{agent.name}: ability action but no ability_name, falling back to wait"
            )
            primary = make_wait(agent.agent_id, "ability without name")
        else:
            ability = agent.attributes.get_ability_by_name(ability_name)
            if ability is None:
                log.warning(
                    f"{agent.name}: unknown ability '{ability_name}', falling back to wait"
                )
                primary = make_wait(agent.agent_id, f"unknown ability: {ability_name}")
            else:
                # Determine if self-targeting
                effects = ability.get("effects", [])
                is_self = (
                    all(e.get("target", "enemy") == "self" for e in effects)
                    if effects
                    else False
                )
                if ability.get("damage", 0) == 0 and is_self:
                    is_self = True

                # Determine if ally-targeting (heal/buff an ally)
                is_ally_target = False
                if not is_self and effects:
                    has_ally_effects = any(e.get("target") == "ally" for e in effects)
                    if has_ally_effects and ability.get("damage", 0) == 0:
                        is_ally_target = True

                if is_self:
                    primary = make_ability(
                        agent.agent_id, None, ability["name"], reasoning
                    )
                elif is_ally_target:
                    # Ally-targeting: self is a valid target
                    target_str = raw.get("target_agent", "")
                    resolved = None
                    if not target_str or target_str == "self":
                        # No target or explicit "self" → target self
                        resolved = agent.agent_id
                    elif target_str in env.agents and env.agents[target_str].is_alive:
                        resolved = target_str
                    else:
                        # Fuzzy name→id resolution (including self)
                        for other in env.alive_agents():
                            if target_str and (
                                target_str.lower() == other.identity.name.lower()
                                or target_str.lower() == other.agent_id.lower()
                            ):
                                resolved = other.agent_id
                                break
                    if resolved:
                        primary = make_ability(
                            agent.agent_id, resolved, ability["name"], reasoning
                        )
                    else:
                        log.warning(
                            f"{agent.name}: invalid ally-ability target '{target_str}', falling back to wait"
                        )
                        primary = make_wait(
                            agent.agent_id, f"invalid ally-ability target: {target_str}"
                        )
                else:
                    target_str = raw.get("target_agent", "")
                    resolved = None
                    if (
                        target_str
                        and target_str in env.agents
                        and env.agents[target_str].is_alive
                    ):
                        resolved = target_str
                    else:
                        for other in env.alive_agents():
                            if other.agent_id == agent.agent_id:
                                continue
                            if target_str and (
                                target_str.lower() == other.identity.name.lower()
                                or target_str.lower() == other.agent_id.lower()
                            ):
                                resolved = other.agent_id
                                break
                    if resolved:
                        primary = make_ability(
                            agent.agent_id, resolved, ability["name"], reasoning
                        )
                    else:
                        log.warning(
                            f"{agent.name}: invalid ability target '{target_str}', falling back to wait"
                        )
                        primary = make_wait(
                            agent.agent_id, f"invalid ability target: {target_str}"
                        )

    elif action_str == "move":
        # Legacy: LLM said "move" as primary action — the move was already
        # extracted above, so just use WAIT as the primary action.
        if move_action is None:
            # No tile provided, nothing to do
            primary = make_wait(agent.agent_id, "move with no tile")
        else:
            primary = make_wait(agent.agent_id, reasoning)

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

    # --- Optional free chat ---
    chat_action: CombatAction | None = None
    chat_target = raw.get("chat_target", "")
    chat_message = raw.get("chat_message", "")

    # LLMs sometimes emit JSON null / the string "null" / "none"
    if isinstance(chat_target, str) and chat_target.lower() in ("null", "none", ""):
        chat_target = ""
    if isinstance(chat_message, str) and chat_message.lower() in ("null", "none"):
        chat_message = ""

    if chat_target and chat_message:
        resolved = _resolve_chat_target(chat_target, agent, env)
        if resolved:
            chat_action = make_chat(agent.agent_id, resolved, chat_message, reasoning)
        else:
            log.warning(f"{agent.name}: invalid chat target '{chat_target}'")

    # --- Move ordering ---
    move_order = raw.get("move_order", "before").lower().strip()
    move_after = move_order == "after"

    return CombatDecision(
        primary_action=primary,
        move_action=move_action,
        chat_action=chat_action,
        move_after=move_after,
    )


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
    world_lore: str = "",
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

    system_prompt = build_system_prompt(agent, world_lore=world_lore)

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
        can_ability=ctx.get("can_ability"),
        alliance_statuses=ctx.get("alliance_statuses"),
        eliminated=ctx.get("eliminated"),
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
    world_lore: str = "",
) -> CombatDecision:
    """Async version of decide(). Calls llm.async_complete()."""
    ctx = _gather_context(agent, env, perceptions_text, memories)
    if not ctx:
        return CombatDecision(primary_action=make_wait(agent.agent_id, "no position"))

    system_prompt = build_system_prompt(agent, world_lore=world_lore)

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
        can_ability=ctx.get("can_ability"),
        alliance_statuses=ctx.get("alliance_statuses"),
        eliminated=ctx.get("eliminated"),
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
