"""Serializers — convert simulation objects to JSON-serializable dicts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from world.battle_grid import BattleGrid

if TYPE_CHECKING:
    from agent.agent import Agent
    from cognition.cognitive_loop import CognitiveLoop
    from combat.actions import CombatAction
    from world.environment import ActionResult, Environment


def serialize_agent(agent: Agent, env: Environment) -> dict:
    """Serialize a single agent to a JSON-safe dict."""
    pos = env.world_state.get_position(agent.agent_id)
    x, y = BattleGrid.parse_tile(pos) if pos else (0, 0)
    a = agent.attributes
    return {
        "id": agent.agent_id,
        "name": agent.name,
        "combat_class": agent.identity.combat_class,
        "backstory": agent.identity.backstory,
        "personality": agent.identity.personality_traits,
        "sprite": agent.identity.sprite,
        "x": x,
        "y": y,
        "hp": a.hp,
        "max_hp": a.max_hp,
        "mana": a.mana,
        "max_mana": a.max_mana,
        "atk": a.atk,
        "mgk": a.mgk,
        "spd": a.spd,
        "con": a.con,
        "hit": a.hit,
        "attack_range": a.attack_range,
        "damage_type": a.damage_type,
        "phys_def": a.phys_def,
        "mag_def": a.mag_def,
        "is_alive": a.is_alive,
        "status_effects": [
            {
                "type": e["type"],
                "duration": e["duration"],
                "magnitude": e.get("magnitude", 0),
            }
            for e in a.status_effects
        ],
        "abilities": [
            {
                "name": ab.get("name", "?"),
                "mana_cost": ab.get("mana_cost", 0),
                "damage": ab.get("damage", 0),
                "range": ab.get("range", 0),
                "aoe_pattern": ab.get("aoe_pattern", "single"),
                "cooldown": ab.get("cooldown", 0),
                "current_cd": ab.get("current_cd", 0),
                "description": ab.get("description", ""),
                "tactical_hint": ab.get("tactical_hint", ""),
                "effects": [
                    {
                        "type": eff.get("type", ""),
                        "behavior": eff.get("behavior", ""),
                        "duration": eff.get("duration", 0),
                        "magnitude": eff.get("magnitude", 0),
                        "target": eff.get("target", ""),
                        "category": eff.get("category", ""),
                        "chance": eff.get("chance", 0),
                    }
                    for eff in ab.get("effects", [])
                ],
            }
            for ab in a.abilities
        ],
    }


def serialize_social(agent: Agent) -> dict:
    """Serialize an agent's social model."""
    rels = agent.social.all_relationships()
    return {
        agent_id: {
            "agent_id": rel.agent_id,
            "agent_name": rel.agent_name,
            "disposition": round(rel.disposition, 3),
            "trust": round(rel.trust, 3),
            "alliance_declared": rel.alliance_declared,
            "betrayal_count": rel.betrayal_count,
            "interaction_count": rel.interaction_count,
        }
        for agent_id, rel in rels.items()
    }


def serialize_snapshot(
    env: Environment,
    phase: str,
    cognitive_loop: CognitiveLoop | None = None,
) -> dict:
    """Build a full state snapshot for new WebSocket connections."""
    agents = {}
    social = {}
    for agent in env.agents.values():
        agents[agent.agent_id] = serialize_agent(agent, env)
        social[agent.agent_id] = serialize_social(agent)

    turn_order = (
        list(env.turn_manager.turn_order) if env.turn_manager.turn_order else []
    )
    current = env.turn_manager.current_agent_id

    return {
        "type": "snapshot",
        "grid": {
            "width": env.grid.width,
            "height": env.grid.height,
            "tiles": env.grid.serialize_tiles(),
        },
        "agents": agents,
        "social": social,
        "phase": phase,
        "round": env.turn_manager.round_number,
        "turn_order": turn_order,
        "active_agent": current,
    }


def serialize_action_event(
    action: CombatAction,
    result: ActionResult,
    env: Environment,
) -> dict:
    """Serialize a resolved action into an event dict."""
    # Build state delta: agent states that changed
    state_delta = {}
    # Always include the acting agent
    agent = env.agents.get(action.agent_id)
    if agent:
        state_delta[action.agent_id] = serialize_agent(agent, env)
    # Include target if present
    if action.target_agent and action.target_agent in env.agents:
        target = env.agents[action.target_agent]
        state_delta[action.target_agent] = serialize_agent(target, env)

    return {
        "type": "action",
        "agent_id": action.agent_id,
        "action_type": action.action_type.value,
        "target_agent": action.target_agent,
        "target_tile": action.target_tile,
        "ability_name": action.ability_name,
        "reasoning": action.reasoning,
        "success": result.success,
        "description": result.description,
        "details": result.details,
        "state_delta": state_delta,
    }


def serialize_cognitive(
    agent_id: str,
    cognitive_loop: CognitiveLoop,
) -> dict:
    """Serialize cognitive state for the mind view panel."""
    state = cognitive_loop.get_state(agent_id)
    if state is None:
        return {
            "type": "cognitive",
            "agent_id": agent_id,
            "memory_count": 0,
            "importance": 0,
            "plan": "",
            "reflection": "",
            "reasoning": "",
        }

    plan = cognitive_loop._planner.get_current_plan(agent_id)

    # Get last reflection from memory
    reflection = ""
    for node in reversed(state.memory._nodes):
        if node.memory_type.value == "reflection":
            reflection = node.description
            break

    return {
        "type": "cognitive",
        "agent_id": agent_id,
        "memory_count": len(state.memory),
        "importance": round(state.memory.importance_accumulator, 1),
        "plan": plan or "",
        "reflection": reflection,
        "reasoning": "",
    }


def serialize_dialogue_exchange(exchange) -> dict:
    """Serialize a DialogueExchange."""
    return {
        "speaker": exchange.speaker,
        "speaker_name": exchange.speaker_name,
        "message": exchange.message,
        "disposition_shift": round(exchange.disposition_shift, 3),
        "round_number": exchange.round_number,
    }
