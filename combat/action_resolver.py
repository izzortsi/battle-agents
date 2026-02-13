"""Action resolver — validates and resolves combat actions against the world state.

Implements the damage formula and movement validation from the spec:
  damage = max(0, attacker.attack - target.defense) * uniform(0.8, 1.2)
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

from combat.actions import ActionType, CombatAction
from world.battle_grid import BattleGrid

if TYPE_CHECKING:
    from world.environment import ActionResult, Environment

log = logging.getLogger(__name__)


def resolve(action: CombatAction, env: "Environment") -> "ActionResult":
    """Resolve a CombatAction.  Returns an ActionResult."""
    from world.environment import ActionResult

    match action.action_type:
        case ActionType.MOVE:
            return _resolve_move(action, env)
        case ActionType.ATTACK:
            return _resolve_attack(action, env)
        case ActionType.DEFEND:
            return _resolve_defend(action, env)
        case ActionType.CHAT:
            return _resolve_chat(action, env)
        case ActionType.WAIT:
            return _resolve_wait(action, env)
        case _:
            return ActionResult(
                agent_id=action.agent_id,
                success=False,
                description=f"{action.agent_id} attempted an unimplemented action: {action.action_type.value}.",
            )


def _resolve_move(action: CombatAction, env: "Environment") -> "ActionResult":
    from world.environment import ActionResult

    agent = env.agents[action.agent_id]
    if not action.target_tile:
        return ActionResult(
            agent.agent_id, False, f"{agent.name} tried to move but specified no tile."
        )

    current = env.world_state.get_position(agent.agent_id)
    if current is None:
        return ActionResult(
            agent.agent_id, False, f"{agent.name} has no current position."
        )

    cx, cy = BattleGrid.parse_tile(current)
    tx, ty = BattleGrid.parse_tile(action.target_tile)
    dist = BattleGrid.manhattan(cx, cy, tx, ty)

    # Validate: within move range?
    if dist > agent.attributes.move_range:
        return ActionResult(
            agent.agent_id,
            False,
            f"{agent.name} tried to move to ({tx},{ty}) but it's {dist} tiles away (range: {agent.attributes.move_range}).",
        )

    # Validate: passable?
    if not env.grid.is_passable(tx, ty):
        return ActionResult(
            agent.agent_id,
            False,
            f"{agent.name} tried to move to an impassable tile ({tx},{ty}).",
        )

    # Validate: occupied by another living agent?
    occupants = env.world_state.agents_at(action.target_tile)
    living_occupants = [
        oid
        for oid in occupants
        if oid != agent.agent_id
        and env.agents.get(oid, None)
        and env.agents[oid].is_alive
    ]
    if living_occupants:
        return ActionResult(
            agent.agent_id,
            False,
            f"{agent.name} tried to move to ({tx},{ty}) but it's occupied by {living_occupants[0]}.",
        )

    env.world_state.set_position(agent.agent_id, action.target_tile)
    return ActionResult(
        agent.agent_id,
        True,
        f"{agent.name} moved from ({cx},{cy}) to ({tx},{ty}).",
        details={"from": current, "to": action.target_tile},
    )


def _resolve_attack(action: CombatAction, env: "Environment") -> "ActionResult":
    from world.environment import ActionResult

    agent = env.agents[action.agent_id]
    target_id = action.target_agent
    if not target_id or target_id not in env.agents:
        return ActionResult(
            agent.agent_id, False, f"{agent.name} tried to attack an invalid target."
        )

    target = env.agents[target_id]
    if not target.is_alive:
        return ActionResult(
            agent.agent_id,
            False,
            f"{agent.name} tried to attack {target.name} but they are already dead.",
        )

    # Range check
    a_pos = env.world_state.get_position(agent.agent_id)
    t_pos = env.world_state.get_position(target_id)
    if not a_pos or not t_pos:
        return ActionResult(
            agent.agent_id, False, f"{agent.name} or {target.name} has no position."
        )

    dist = BattleGrid.tile_distance(a_pos, t_pos)
    if dist > agent.attributes.attack_range:
        return ActionResult(
            agent.agent_id,
            False,
            f"{agent.name} tried to attack {target.name} but they are {dist} tiles away (range: {agent.attributes.attack_range}).",
        )

    # Damage calculation: max(0, attack - defense) * uniform(0.8, 1.2)
    effective_defense = target.attributes.get_effective_defense()
    base_damage = max(0, agent.attributes.attack - effective_defense)
    variance = random.uniform(0.8, 1.2)
    damage = int(base_damage * variance)
    actual = target.attributes.take_damage(damage)

    kill_text = ""
    if not target.is_alive:
        env.handle_agent_death(target_id)
        kill_text = f" {target.name} has been slain!"

    return ActionResult(
        agent.agent_id,
        True,
        f"{agent.name} attacked {target.name} for {actual} damage (HP: {target.attributes.hp}/{target.attributes.max_hp}).{kill_text}",
        details={
            "target": target_id,
            "damage": actual,
            "target_hp": target.attributes.hp,
            "killed": not target.is_alive,
        },
    )


def _resolve_defend(action: CombatAction, env: "Environment") -> "ActionResult":
    from world.environment import ActionResult

    agent = env.agents[action.agent_id]

    # Check diminishing returns: halve magnitude for each consecutive defend
    consecutive = sum(
        1 for e in agent.attributes.status_effects if e["type"] == "defend"
    )
    magnitude = 0.5 * (0.5**consecutive)

    agent.attributes.status_effects.append(
        {
            "type": "defend",
            "duration": 1,
            "magnitude": magnitude,
            "source": agent.agent_id,
        }
    )
    env.world_state.add_status(agent.agent_id, "defending")

    return ActionResult(
        agent.agent_id,
        True,
        f"{agent.name} assumes a defensive stance (+{magnitude:.0%} defense).",
        details={"magnitude": magnitude},
    )


def _resolve_chat(action: CombatAction, env: "Environment") -> "ActionResult":
    """Resolve a CHAT action — validates target, returns success.

    The actual dialogue session is run by the cognitive loop, not here.
    The action resolver just validates that the target is valid and alive.
    """
    from world.environment import ActionResult

    agent = env.agents[action.agent_id]
    target_id = action.target_agent
    if not target_id or target_id not in env.agents:
        return ActionResult(
            agent.agent_id,
            False,
            f"{agent.name} tried to chat with an invalid target.",
        )

    target = env.agents[target_id]
    if not target.is_alive:
        return ActionResult(
            agent.agent_id,
            False,
            f"{agent.name} tried to chat with {target.name} but they are dead.",
        )

    msg_preview = (action.message or "...")[:60]
    return ActionResult(
        agent.agent_id,
        True,
        f'{agent.name} initiates dialogue with {target.name}: "{msg_preview}"',
        details={
            "target": target_id,
            "message": action.message or "",
            "action_type": "chat",
        },
    )


def _resolve_wait(action: CombatAction, env: "Environment") -> "ActionResult":
    from world.environment import ActionResult

    agent = env.agents[action.agent_id]
    return ActionResult(agent.agent_id, True, f"{agent.name} waits.")
