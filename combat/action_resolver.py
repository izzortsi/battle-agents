"""Action resolver — validates and resolves combat actions against the world state.

CT-inspired damage formula:
  raw  = stat×atk_mult − def×def_mult
  roll = raw × uniform(var_low, var_high)
  crit = 2× damage (chance based on SPD)
  hit  = HIT − SPD + base_bonus  (clamped floor..ceiling, rolled as %)
  counter = HIT-based chance for defender to strike back at half damage
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent.attributes import get_balance
from combat.actions import ActionType, CombatAction
from world.battle_grid import BattleGrid

if TYPE_CHECKING:
    from world.environment import ActionResult, Environment

log = logging.getLogger(__name__)


@dataclass
class AttackOutcome:
    """Rich result of an attack resolution, used by runner for counter-attacks."""

    damage: int = 0
    hit: bool = True
    crit: bool = False
    counter: bool = False
    counter_damage: int = 0
    killed: bool = False


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


def _calc_hit_chance(attacker_hit: int, defender_spd: int) -> int:
    """Compute accuracy percentage (clamped)."""
    b = get_balance()
    raw = attacker_hit - defender_spd + b.hit_base_bonus
    return max(b.hit_floor, min(b.hit_ceiling, raw))


def _calc_crit_chance(attacker_spd: int) -> float:
    """Compute critical hit chance as a percentage."""
    b = get_balance()
    return b.crit_base_chance + b.crit_per_spd * attacker_spd


def _calc_counter_chance(defender_hit: int) -> float:
    """Compute counter-attack chance as a percentage."""
    b = get_balance()
    return b.counter_base_chance + b.counter_per_hit * defender_hit


def _calc_damage(
    atk_stat: int,
    def_stat: int,
    is_crit: bool = False,
) -> int:
    """CT-inspired damage: stat×mult − def×def_mult, with variance and optional crit."""
    b = get_balance()
    raw = atk_stat * b.atk_multiplier - def_stat * b.def_multiplier
    raw = max(1, raw)  # minimum 1 raw damage
    variance = random.uniform(b.damage_variance_low, b.damage_variance_high)
    damage = raw * variance
    if is_crit:
        damage *= b.crit_multiplier
    return max(1, int(damage))


def _calc_counter_damage(
    defender_atk_stat: int,
    attacker_def_stat: int,
) -> int:
    """Counter-attack deals a fraction of normal damage (no crit, no variance)."""
    b = get_balance()
    raw = defender_atk_stat * b.atk_multiplier - attacker_def_stat * b.def_multiplier
    raw = max(1, raw)
    return max(1, int(raw * b.counter_damage_multiplier))


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

    # --- Hit / Miss roll ---
    hit_chance = _calc_hit_chance(agent.attributes.hit, target.attributes.spd)
    hit_roll = random.randint(1, 100)
    if hit_roll > hit_chance:
        # Miss!
        return ActionResult(
            agent.agent_id,
            True,  # action succeeded (it was a valid attack), just missed
            f"{agent.name} attacked {target.name} but MISSED! ({hit_chance}% accuracy)",
            details={
                "target": target_id,
                "damage": 0,
                "hit": False,
                "target_hp": target.attributes.hp,
                "killed": False,
            },
        )

    # --- Crit roll ---
    crit_chance = _calc_crit_chance(agent.attributes.spd)
    is_crit = random.uniform(0, 100) < crit_chance

    # --- Determine damage type and pick correct defense ---
    dmg_type = agent.attributes.damage_type
    effective_def = target.attributes.get_effective_defense(dmg_type)

    # --- Damage calculation (CT formula) ---
    damage = _calc_damage(agent.attributes.damage_stat, effective_def, is_crit)
    actual = target.attributes.take_damage(damage)

    # --- Counter-attack roll ---
    counter = False
    counter_dmg = 0
    if target.is_alive and dist <= target.attributes.attack_range:
        counter_chance = _calc_counter_chance(target.attributes.hit)
        if random.uniform(0, 100) < counter_chance:
            counter = True
            target_dmg_type = target.attributes.damage_type
            attacker_def = agent.attributes.get_effective_defense(target_dmg_type)
            counter_dmg = _calc_counter_damage(
                target.attributes.damage_stat, attacker_def
            )
            agent.attributes.take_damage(counter_dmg)

    # --- Build description ---
    crit_text = " CRITICAL HIT!" if is_crit else ""
    kill_text = ""
    if not target.is_alive:
        env.handle_agent_death(target_id)
        kill_text = f" {target.name} has been slain!"

    counter_text = ""
    if counter:
        counter_kill = ""
        if not agent.is_alive:
            env.handle_agent_death(agent.agent_id)
            counter_kill = f" {agent.name} has been slain by the counter!"
        counter_text = (
            f" {target.name} counters for {counter_dmg} damage!{counter_kill}"
        )

    desc = (
        f"{agent.name} attacked {target.name} for {actual} {dmg_type} damage "
        f"(HP: {target.attributes.hp}/{target.attributes.max_hp}).{crit_text}"
        f"{kill_text}{counter_text}"
    )

    return ActionResult(
        agent.agent_id,
        True,
        desc,
        details={
            "target": target_id,
            "damage": actual,
            "hit": True,
            "crit": is_crit,
            "damage_type": dmg_type,
            "target_hp": target.attributes.hp,
            "killed": not target.is_alive,
            "counter": counter,
            "counter_damage": counter_dmg,
        },
    )


def _resolve_defend(action: CombatAction, env: "Environment") -> "ActionResult":
    from world.environment import ActionResult

    agent = env.agents[action.agent_id]
    bal = get_balance()

    # Check diminishing returns: halve magnitude for each consecutive defend
    consecutive = sum(
        1 for e in agent.attributes.status_effects if e["type"] == "defend"
    )
    magnitude = bal.defend_bonus_fraction * (bal.defend_diminishing ** consecutive)

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
