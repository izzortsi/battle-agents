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
from combat.aoe import get_affected_tiles
from combat.status_registry import get_behavior
from world.alliance_resolver import AllianceStatus, resolve_alliance
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
        case ActionType.ABILITY:
            return _resolve_ability(action, env)
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

    # Check for prevent_move statuses (root, freeze, entangle, etc.)
    for eff in agent.attributes.status_effects:
        if get_behavior(eff["type"]) == "prevent_move":
            return ActionResult(
                agent.agent_id,
                False,
                f"{agent.name} is {eff['type']}ed and cannot move!",
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

    # --- Blind check (miss_chance behavior on attacker) ---
    for eff in agent.attributes.status_effects:
        if get_behavior(eff["type"]) == "miss_chance":
            if random.random() < eff.get("magnitude", 0.3):
                return ActionResult(
                    agent.agent_id,
                    True,
                    f"{agent.name} attacked {target.name} but is {eff['type']}ed and MISSED!",
                    details={
                        "target": target_id,
                        "damage": 0,
                        "hit": False,
                        "target_hp": target.attributes.hp,
                        "killed": False,
                    },
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
    magnitude = bal.defend_bonus_fraction * (bal.defend_diminishing**consecutive)

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


# ===================================================================
# Ability resolution
# ===================================================================


def _apply_damage(
    raw_damage: int,
    attacker: "Agent",
    target: "Agent",
    damage_type: str | None = None,
) -> int:
    """Apply ability damage through the modifier pipeline and return actual damage.

    Pipeline:
      1. boost_outgoing_damage  on attacker:  raw * (1 + magnitude)
      2. reduce_outgoing_damage on attacker:  raw * (1 - magnitude)
      3. reduce_incoming_damage on target:    raw * (1 - magnitude)
      4. Defend buff already factored into effective_defense if relevant
      5. Floor at 1
    """
    dmg = float(raw_damage)

    # Attacker outgoing modifiers
    for eff in attacker.attributes.status_effects:
        beh = get_behavior(eff["type"])
        if beh == "boost_outgoing_damage":
            dmg *= 1.0 + eff.get("magnitude", 0.2)
        elif beh == "reduce_outgoing_damage":
            dmg *= 1.0 - eff.get("magnitude", 0.2)

    # Target incoming modifiers
    for eff in target.attributes.status_effects:
        beh = get_behavior(eff["type"])
        if beh == "reduce_incoming_damage":
            dmg *= 1.0 - eff.get("magnitude", 0.2)

    final = max(1, int(dmg))
    actual = target.attributes.take_damage(final)
    return actual


def _resolve_effect(
    effect: dict,
    caster: "Agent",
    target: "Agent | None",
    env: "Environment",
) -> str:
    """Dispatch a single ability effect.  Returns a description string.

    Routes by category:
      movement — find empty adjacent tile, move caster
      heal     — restore HP based on magnitude * max_hp (self, ally, or enemy)
      buff     — append status to caster or ally (unconditional)
      debuff   — roll chance, append to target on success
    """
    category = effect.get("category", "debuff")
    effect_target = effect.get("target", "enemy")
    magnitude = effect.get("magnitude", 0.2)
    duration = effect.get("duration", 1)
    chance = effect.get("chance", 1.0)
    etype = effect.get("type", "unknown")

    # --- Movement ---
    if category == "movement":
        # Move the caster to an adjacent passable, unoccupied tile
        pos = env.world_state.get_position(caster.agent_id)
        if not pos:
            return f"{caster.name} tried to move but has no position."
        cx, cy = BattleGrid.parse_tile(pos)
        adj = env.grid.adjacent_tiles(cx, cy)
        for ax, ay in adj:
            tile_key = BattleGrid.tile_key(ax, ay)
            occupants = env.world_state.agents_at(tile_key)
            living = [
                o
                for o in occupants
                if o != caster.agent_id and env.agents.get(o) and env.agents[o].is_alive
            ]
            if not living:
                env.world_state.set_position(caster.agent_id, tile_key)
                return f"{caster.name} dashes to ({ax},{ay})."
        return f"{caster.name} tried to dash but all adjacent tiles are blocked."

    # --- Heal ---
    if category == "heal" or etype == "heal":
        if effect_target == "self":
            recipient = caster
        elif effect_target == "ally" and target is not None:
            recipient = target
        elif target is not None:
            recipient = target
        else:
            recipient = caster
        heal_amount = int(recipient.attributes.max_hp * magnitude)
        actual = recipient.attributes.heal(heal_amount)
        # Social model update: if healing an ally (not self)
        if recipient.agent_id != caster.agent_id:
            turn = env.turn_manager.global_turn
            recipient.social.on_healed_by(
                healer_id=caster.agent_id,
                turn=turn,
                amount=actual,
                agent_name=caster.name,
            )
        return (
            f"{recipient.name} heals for {actual} HP "
            f"({recipient.attributes.hp}/{recipient.attributes.max_hp})."
        )

    # --- Buff (applied to caster or ally) ---
    if category == "buff" or (effect_target == "self" and category != "debuff"):
        if effect_target == "ally" and target is not None:
            buff_recipient = target
        else:
            buff_recipient = caster
        buff_recipient.attributes.status_effects.append(
            {
                "type": etype,
                "duration": duration,
                "magnitude": magnitude,
                "source": caster.agent_id,
            }
        )
        return f"{buff_recipient.name} gains {etype} ({duration} turns)."

    # --- Debuff (applied to target, roll chance) ---
    if target is None:
        return ""
    if random.random() < chance:
        target.attributes.status_effects.append(
            {
                "type": etype,
                "duration": duration,
                "magnitude": magnitude,
                "source": caster.agent_id,
            }
        )
        return f"{target.name} is afflicted with {etype} ({duration} turns)!"
    else:
        return f"{target.name} resists {etype}!"


def _resolve_ability(action: CombatAction, env: "Environment") -> "ActionResult":
    """Resolve an ABILITY action."""
    from world.environment import ActionResult

    if TYPE_CHECKING:
        from agent.agent import Agent

    agent = env.agents[action.agent_id]
    ability_name = action.ability_name or ""

    # --- Validate ability exists ---
    ability = agent.attributes.get_ability_by_name(ability_name)
    if ability is None:
        return ActionResult(
            agent.agent_id,
            False,
            f"{agent.name} tried to use unknown ability '{ability_name}'.",
        )

    # --- Off cooldown? ---
    if ability.get("current_cd", 0) > 0:
        return ActionResult(
            agent.agent_id,
            False,
            f"{agent.name} tried to use {ability['name']} but it's on cooldown ({ability['current_cd']} turns).",
        )

    # --- Mana sufficient? ---
    mana_cost = ability.get("mana_cost", 0)
    if not agent.attributes.spend_mana(mana_cost):
        return ActionResult(
            agent.agent_id,
            False,
            f"{agent.name} tried to use {ability['name']} but lacks mana ({agent.attributes.mana}/{mana_cost}).",
        )

    # --- Determine if self-targeting ---
    effects = ability.get("effects", [])
    is_self_targeting = (
        all(e.get("target", "enemy") == "self" for e in effects) if effects else False
    )
    # Also self-target if ability has no damage and no enemy-targeting effects
    if ability.get("damage", 0) == 0 and is_self_targeting:
        is_self_targeting = True

    # --- Determine if ally-targeting ---
    is_ally_targeting = False
    if effects and not is_self_targeting:
        has_ally_effects = any(e.get("target") == "ally" for e in effects)
        if has_ally_effects and ability.get("damage", 0) == 0:
            is_ally_targeting = True

    # --- Resolve target ---
    target = None
    target_pos = None
    if is_self_targeting:
        # Self-targeting: target is the caster
        target = agent
        target_pos = env.world_state.get_position(agent.agent_id)
    elif is_ally_targeting:
        # Ally-targeting: target_agent can be self or another agent
        target_id = action.target_agent
        if not target_id or target_id == agent.agent_id:
            # Target self
            target = agent
            target_pos = env.world_state.get_position(agent.agent_id)
        elif target_id in env.agents and env.agents[target_id].is_alive:
            target = env.agents[target_id]
            target_pos = env.world_state.get_position(target_id)
        else:
            agent.attributes.mana = min(
                agent.attributes.max_mana, agent.attributes.mana + mana_cost
            )
            return ActionResult(
                agent.agent_id,
                False,
                f"{agent.name} tried to use {ability['name']} on an invalid ally.",
            )
    else:
        target_id = action.target_agent
        if not target_id or target_id not in env.agents:
            # Refund mana on invalid target
            agent.attributes.mana = min(
                agent.attributes.max_mana, agent.attributes.mana + mana_cost
            )
            return ActionResult(
                agent.agent_id,
                False,
                f"{agent.name} tried to use {ability['name']} on an invalid target.",
            )
        target = env.agents[target_id]
        if not target.is_alive:
            agent.attributes.mana = min(
                agent.attributes.max_mana, agent.attributes.mana + mana_cost
            )
            return ActionResult(
                agent.agent_id,
                False,
                f"{agent.name} tried to use {ability['name']} on {target.name} but they are dead.",
            )
        target_pos = env.world_state.get_position(target_id)

    # --- Range check (skip for self-targeting) ---
    agent_pos = env.world_state.get_position(agent.agent_id)
    if not agent_pos:
        return ActionResult(agent.agent_id, False, f"{agent.name} has no position.")

    if not is_self_targeting:
        if not target_pos:
            agent.attributes.mana = min(
                agent.attributes.max_mana, agent.attributes.mana + mana_cost
            )
            return ActionResult(
                agent.agent_id,
                False,
                f"{target.name} has no position.",
            )
        dist = BattleGrid.tile_distance(agent_pos, target_pos)
        ability_range = ability.get("range", 1)
        if dist > ability_range:
            agent.attributes.mana = min(
                agent.attributes.max_mana, agent.attributes.mana + mana_cost
            )
            return ActionResult(
                agent.agent_id,
                False,
                f"{agent.name} tried to use {ability['name']} on {target.name} but they are {dist} tiles away (range: {ability_range}).",
            )

    # --- Blind check (miss_chance on caster) ---
    for eff in agent.attributes.status_effects:
        if get_behavior(eff["type"]) == "miss_chance":
            if random.random() < eff.get("magnitude", 0.3):
                # Set cooldown regardless of miss
                ability["current_cd"] = ability.get("cooldown", 0)
                return ActionResult(
                    agent.agent_id,
                    True,
                    f"{agent.name} uses {ability['name']} but is {eff['type']}ed and MISSES!",
                    details={
                        "ability": ability["name"],
                        "damage": 0,
                        "hit": False,
                    },
                )

    # --- Compute AoE tiles ---
    ax, ay = BattleGrid.parse_tile(agent_pos)
    origin = (ax, ay)
    if target_pos:
        tx, ty = BattleGrid.parse_tile(target_pos)
        target_tile = (tx, ty)
    else:
        target_tile = origin

    aoe_pattern = ability.get("aoe_pattern", "single")
    affected_tiles = get_affected_tiles(origin, target_tile, aoe_pattern, env.grid)

    # --- Apply damage and effects to affected agents ---
    base_damage = ability.get("damage", 0)
    log_parts: list[str] = [f"{agent.name} uses {ability['name']}!"]
    total_damage = 0
    kills: list[str] = []

    # Collect all agents on affected tiles
    affected_agents: list["Agent"] = []
    for tile_xy in affected_tiles:
        tile_key = BattleGrid.tile_key(*tile_xy)
        for occupant_id in env.world_state.agents_at(tile_key):
            occupant = env.agents.get(occupant_id)
            if occupant and occupant.is_alive and occupant.agent_id != agent.agent_id:
                if occupant not in affected_agents:
                    affected_agents.append(occupant)

    # For self-targeting abilities with no enemy effects, just apply effects to self
    if is_self_targeting:
        for effect in effects:
            desc = _resolve_effect(effect, agent, None, env)
            if desc:
                log_parts.append(desc)
    elif is_ally_targeting:
        # Ally-targeting: apply heal/buff effects to the targeted ally
        for effect in effects:
            desc = _resolve_effect(effect, agent, target, env)
            if desc:
                log_parts.append(desc)
    else:
        if not affected_agents and base_damage > 0:
            log_parts.append("But no enemies are caught in the area.")
        else:
            for affected in affected_agents:
                # Determine alliance status for AoE friendly fire reduction
                is_ally = False
                if agent.agent_id != affected.agent_id:
                    status = resolve_alliance(
                        agent.social,
                        affected.social,
                        agent.agent_id,
                        affected.agent_id,
                    )
                    is_ally = status == AllianceStatus.ALLIED

                # Dodge check: (target.spd - attacker.spd) * 0.03
                dodge_chance = max(
                    0.0, (affected.attributes.spd - agent.attributes.spd) * 0.03
                )
                if random.random() < dodge_chance:
                    log_parts.append(f"{affected.name} dodges!")
                    continue

                # Apply damage
                if base_damage > 0:
                    effective_damage = base_damage
                    if is_ally:
                        # Allied targets take 50% damage from AoE friendly fire
                        effective_damage = max(1, base_damage // 2)
                    actual = _apply_damage(effective_damage, agent, affected)
                    total_damage += actual
                    ff_tag = " (friendly fire!)" if is_ally else ""
                    log_parts.append(
                        f"{affected.name} takes {actual} damage{ff_tag} "
                        f"({affected.attributes.hp}/{affected.attributes.max_hp} HP)."
                    )
                    if not affected.is_alive:
                        env.handle_agent_death(affected.agent_id)
                        kills.append(affected.name)
                        log_parts.append(f"{affected.name} has been slain!")
                        continue  # Dead — don't apply effects

                # Apply effects to this target
                for effect in effects:
                    eff_target = effect.get("target", "enemy")
                    if eff_target == "self":
                        # Self-targeting effect on an offensive ability (e.g., self-buff)
                        desc = _resolve_effect(effect, agent, None, env)
                    elif is_ally and effect.get("category", "debuff") == "debuff":
                        # Skip debuffs on allied targets from AoE friendly fire
                        continue
                    else:
                        desc = _resolve_effect(effect, agent, affected, env)
                    if desc:
                        log_parts.append(desc)

    # --- Set cooldown (always, even on miss — but miss returns early above) ---
    ability["current_cd"] = ability.get("cooldown", 0)

    description = " ".join(log_parts)
    return ActionResult(
        agent.agent_id,
        True,
        description,
        details={
            "ability": ability["name"],
            "damage": total_damage,
            "hit": True,
            "kills": kills,
            "aoe_pattern": aoe_pattern,
            "affected_count": len(affected_agents),
        },
    )
