"""Battle-Agents runner — main entry point.

Phase 4: Full two-phase simulation: pre-battle social phase → combat.
Agents perceive, remember, retrieve, reflect, plan, and decide using an LLM.
Memory and social models persist across both phases.

Usage:
    python runner.py             # LLM-driven (pre-battle + combat)
    python runner.py --random    # Phase 1 random-action fallback (combat only)
    python runner.py --no-social # LLM combat only, skip pre-battle
    python runner.py --generate  # Generate a new character via LLM
    python runner.py --generate --save  # Generate + save to config/characters/
    python runner.py --generate --battle  # Generate, save, then run a full battle
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
from pathlib import Path

from agent.agent import Agent
from combat.actions import (
    ActionType,
    CombatAction,
    make_attack,
    make_defend,
    make_move,
    make_wait,
)
from combat.status_registry import get_behavior
from config_loader import (
    load_all_characters,
    load_balance_config,
    load_game_config,
    load_llm_config,
)
from world.battle_grid import BattleGrid
from world.environment import Environment

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


# ==========================================================================
# Phase 1 fallback: random actions
# ==========================================================================


def pick_random_action(agent: Agent, env: Environment) -> CombatAction:
    """Select a random valid combat action, biased toward attacking and closing distance."""
    pos = env.world_state.get_position(agent.agent_id)
    if pos is None:
        return make_wait(agent.agent_id, "No position")

    ax, ay = BattleGrid.parse_tile(pos)

    # ATTACK: any living agent in attack range — always prefer if available
    attack_actions: list[CombatAction] = []
    for other in env.alive_agents():
        if other.agent_id == agent.agent_id:
            continue
        other_pos = env.world_state.get_position(other.agent_id)
        if other_pos is None:
            continue
        dist = BattleGrid.tile_distance(pos, other_pos)
        if dist <= agent.attributes.attack_range:
            attack_actions.append(
                make_attack(agent.agent_id, other.agent_id, "random attack")
            )

    if attack_actions:
        if random.random() < 0.8:
            return random.choice(attack_actions)

    # MOVE: bias toward nearest enemy
    move_actions: list[CombatAction] = []
    adjacent = env.grid.adjacent_tiles(ax, ay)
    nearest_enemy_pos: tuple[int, int] | None = None
    nearest_dist = float("inf")
    for other in env.alive_agents():
        if other.agent_id == agent.agent_id:
            continue
        other_pos = env.world_state.get_position(other.agent_id)
        if other_pos is None:
            continue
        ex, ey = BattleGrid.parse_tile(other_pos)
        d = BattleGrid.manhattan(ax, ay, ex, ey)
        if d < nearest_dist:
            nearest_dist = d
            nearest_enemy_pos = (ex, ey)

    for tx, ty in adjacent:
        tile_key = BattleGrid.tile_key(tx, ty)
        occupants = env.world_state.agents_at(tile_key)
        living_occ = [
            o
            for o in occupants
            if o != agent.agent_id and env.agents.get(o) and env.agents[o].is_alive
        ]
        if not living_occ:
            move_actions.append(make_move(agent.agent_id, tile_key, "random move"))

    if move_actions and nearest_enemy_pos and random.random() < 0.7:
        ex, ey = nearest_enemy_pos
        best_move = min(
            move_actions,
            key=lambda a: BattleGrid.manhattan(
                *BattleGrid.parse_tile(a.target_tile or "0_0"), ex, ey
            ),
        )
        return best_move

    possible: list[tuple[CombatAction, float]] = []
    for m in move_actions:
        possible.append((m, 1.0))
    for a in attack_actions:
        possible.append((a, 3.0))
    possible.append((make_defend(agent.agent_id, "random defend"), 0.5))
    possible.append((make_wait(agent.agent_id, "random wait"), 0.2))

    actions, weights = zip(*possible)
    return random.choices(actions, weights=weights, k=1)[0]


# ==========================================================================
# Death broadcast helper
# ==========================================================================


def _broadcast_kills(
    result: "ActionResult",
    agent: Agent,
    env: Environment,
    round_num: int,
    cognitive_loop: "CognitiveLoop | None",
) -> None:
    """Check an action result for kills and broadcast death memories.

    Handles three kill sources:
      - Direct kill (attack or single-target ability): details["killed"] is True
      - AoE ability kills: details["kills"] is a non-empty list
      - Counter-attack kill: details["counter"] and attacker died
    """
    if cognitive_loop is None or not result.success:
        return

    details = result.details

    # Direct kill (attack or ability hit that killed the target)
    if details.get("killed"):
        target_id = details.get("target")
        target_agent = env.agents.get(target_id) if target_id else None
        if target_agent:
            method = details.get("ability", "basic attack")
            cognitive_loop.broadcast_death(
                dead_agent=target_agent,
                killer_name=agent.name,
                method=method,
                round_num=round_num,
                env=env,
            )

    # AoE ability kills (multiple possible)
    kills_list = details.get("kills", [])
    if kills_list and not details.get("killed"):
        # kills is a list of *names*; find agents by name
        ability_name = details.get("ability", "ability")
        for dead_name in kills_list:
            for a in env.agents.values():
                if a.name == dead_name and not a.is_alive:
                    cognitive_loop.broadcast_death(
                        dead_agent=a,
                        killer_name=agent.name,
                        method=ability_name,
                        round_num=round_num,
                        env=env,
                    )
                    break

    # Counter-attack kill (the attacker was killed by the counter)
    if details.get("counter") and details.get("counter_damage", 0) > 0:
        if not agent.is_alive:
            target_id = details.get("target")
            target_agent = env.agents.get(target_id) if target_id else None
            counter_killer_name = target_agent.name if target_agent else "unknown"
            cognitive_loop.broadcast_death(
                dead_agent=agent,
                killer_name=counter_killer_name,
                method="counter-attack",
                round_num=round_num,
                env=env,
            )


# ==========================================================================
# Grid display and agent placement
# ==========================================================================


def place_agents(agents: list[Agent], env: Environment, min_dist: int = 3) -> None:
    """Place agents on random passable tiles with minimum separation."""
    placed: list[tuple[int, int]] = []
    passable = list(env.grid.all_passable())
    random.shuffle(passable)

    for agent in agents:
        for x, y in passable:
            if all(BattleGrid.manhattan(x, y, px, py) >= min_dist for px, py in placed):
                env.register_agent(agent, x, y)
                placed.append((x, y))
                log.info(f"  Placed {agent.name} at ({x}, {y})")
                break


def print_grid(env: Environment) -> None:
    """Print a simple ASCII representation of the grid."""
    grid = env.grid
    occupied: dict[tuple[int, int], str] = {}
    for agent in env.agents.values():
        if not agent.is_alive:
            continue
        pos = env.world_state.get_position(agent.agent_id)
        if pos:
            xy = BattleGrid.parse_tile(pos)
            occupied[xy] = agent.name[0].upper()

    lines = []
    lines.append("  " + "".join(f"{x:2}" for x in range(grid.width)))
    for y in range(grid.height):
        row = f"{y:2} "
        for x in range(grid.width):
            if (x, y) in occupied:
                row += f" {occupied[(x, y)]}"
            else:
                row += f" {grid.tile_char(x, y)}"
        lines.append(row)
    log.info("\n".join(lines))


def print_status(env: Environment) -> None:
    """Print the status of all agents."""
    for agent in env.agents.values():
        alive_str = "ALIVE" if agent.is_alive else "DEAD "
        pos = env.world_state.get_position(agent.agent_id) or "???"
        log.info(f"  [{alive_str}] {agent.status_summary()} @ {pos}")


def print_social_stats(env: Environment) -> None:
    """Print social model stats for all agents."""
    log.info(f"\n--- Social Model Stats ---")
    for agent in env.agents.values():
        rels = agent.social.all_relationships()
        if rels:
            log.info(f"  {agent.name}:")
            for rel in rels.values():
                status = (
                    "ally"
                    if rel.disposition > 0.5
                    else ("enemy" if rel.disposition < -0.3 else "neutral")
                )
                log.info(
                    f"    -> {rel.agent_name}: {rel.disposition:+.2f} ({status}), "
                    f"trust={rel.trust:.2f}, interactions={rel.interaction_count}"
                )


# ==========================================================================
# LLM setup (shared by pre-battle and combat)
# ==========================================================================


def create_adapter(llm_cfg: dict):
    """Create an LLM adapter from config.

    Reads the ``default_adapter`` key (e.g. "openrouter/gemini-3-flash",
    "openai/gpt-4o", "anthropic/sonnet") to pick the provider and model,
    then instantiates the appropriate adapter class.

    Returns (adapter, model_id).
    """
    default = llm_cfg.get("default_adapter", "openrouter/gemini-3-flash")
    parts = default.split("/", 1)
    provider_key = parts[0]
    model_alias = parts[1] if len(parts) > 1 else None

    adapters_cfg = llm_cfg.get("adapters", {})
    provider_cfg = adapters_cfg.get(provider_key, {})
    models_cfg = provider_cfg.get("models", {})

    # Resolve model_id from the alias (or first model in config)
    model_id = None
    if model_alias and model_alias in models_cfg:
        model_id = models_cfg[model_alias].get("model_id")
    if model_id is None:
        for _name, mcfg in models_cfg.items():
            model_id = mcfg.get("model_id")
            break

    if provider_key == "openrouter":
        from llm.openrouter_adapter import OpenRouterAdapter

        model_id = model_id or "google/gemini-2.5-flash"
        adapter = OpenRouterAdapter(model=model_id)

    elif provider_key == "openai":
        from llm.openai_adapter import OpenAIAdapter

        model_id = model_id or "gpt-4o"
        adapter = OpenAIAdapter(model=model_id)

    elif provider_key == "anthropic":
        from llm.anthropic_oauth_adapter import AnthropicOAuthAdapter

        model_id = model_id or "claude-sonnet-4-5-20250929"
        auth_mode = provider_cfg.get("auth", "oauth")
        if auth_mode == "oauth":
            adapter = AnthropicOAuthAdapter(model=model_id)
        else:
            # Future: API key-based Anthropic adapter
            raise ValueError(
                f"Anthropic auth mode '{auth_mode}' not yet supported. Use 'oauth'."
            )
    else:
        raise ValueError(
            f"Unknown LLM provider '{provider_key}'. "
            f"Supported: openrouter, openai, anthropic"
        )

    log.info(f"LLM adapter: {adapter.name}")
    return adapter, model_id


def _create_single_adapter(provider_key: str, model_cfg: dict, provider_cfg: dict):
    """Create a single LLM adapter from provider key and model config."""
    model_id = model_cfg.get("model_id")

    if provider_key == "openrouter":
        from llm.openrouter_adapter import OpenRouterAdapter

        model_id = model_id or "google/gemini-2.5-flash"
        return OpenRouterAdapter(model=model_id)

    elif provider_key == "openai":
        from llm.openai_adapter import OpenAIAdapter

        model_id = model_id or "gpt-4o"
        return OpenAIAdapter(model=model_id)

    elif provider_key == "anthropic":
        from llm.anthropic_oauth_adapter import AnthropicOAuthAdapter

        model_id = model_id or "claude-sonnet-4-5-20250929"
        auth_mode = provider_cfg.get("auth", "oauth")
        if auth_mode == "oauth":
            return AnthropicOAuthAdapter(model=model_id)
        else:
            raise ValueError(
                f"Anthropic auth mode '{auth_mode}' not yet supported. Use 'oauth'."
            )
    else:
        raise ValueError(
            f"Unknown LLM provider '{provider_key}'. "
            f"Supported: openrouter, openai, anthropic"
        )


def create_model_registry(llm_cfg: dict):
    """Create all configured adapters and register them in a ModelRegistry.

    Returns (registry, default_adapter).
    """
    from llm.adapter import ModelRegistry

    registry = ModelRegistry()
    adapters_cfg = llm_cfg.get("adapters", {})

    for provider_key, provider_cfg in adapters_cfg.items():
        models_cfg = provider_cfg.get("models", {})
        for model_alias, model_cfg in models_cfg.items():
            key = f"{provider_key}/{model_alias}"
            try:
                adapter = _create_single_adapter(provider_key, model_cfg, provider_cfg)
                registry.register(key, adapter)
                log.info(f"  Registered adapter: {key}")
            except Exception as e:
                log.warning(f"  Skipped adapter {key}: {e}")

    default_key = llm_cfg.get("default_adapter", "openrouter/gemini-2.5-flash-free")
    if default_key in registry:
        registry.set_default(default_key)
    elif len(registry) > 0:
        # Fallback: use first available adapter
        first_key = registry.available[0]
        registry.set_default(first_key)
        log.warning(f"  Default adapter '{default_key}' not found, using '{first_key}'")

    default_adapter = registry.get()
    return registry, default_adapter


def build_routing_dict(llm_cfg: dict, registry) -> dict:
    """Build a role -> LLMAdapter mapping from config routing section.

    Config routing values are adapter keys like "openrouter/gemini-3-flash".
    Falls back gracefully: unknown keys are skipped (CognitiveLoop uses default).
    """
    from llm.adapter import LLMAdapter

    routing_cfg = llm_cfg.get("routing", {})
    routing: dict[str, LLMAdapter] = {}

    for role, adapter_key in routing_cfg.items():
        if adapter_key in ("heuristic",):
            continue  # special non-LLM roles
        if adapter_key in registry:
            routing[role] = registry.get(adapter_key)
        else:
            log.debug(
                f"  Routing role '{role}' -> '{adapter_key}' not in registry, using default"
            )

    return routing


def setup_cognitive_loop(game_cfg: dict) -> tuple:
    """Create and configure the LLM adapter and CognitiveLoop.

    Returns (cognitive_loop, model_id).
    """
    from cognition.cognitive_loop import CognitiveLoop
    from cognition.embeddings import create_embedding_cache

    llm_cfg = load_llm_config()
    registry, default_adapter = create_model_registry(llm_cfg)
    model_id = default_adapter.name

    # Build per-aspect routing dict
    routing = build_routing_dict(llm_cfg, registry)

    # Create embedding cache from config (None if provider is "none")
    embedding_cfg = llm_cfg.get("embedding", {})
    embedding_cache = create_embedding_cache(embedding_cfg, llm_cfg)

    combat_cfg = game_cfg.get("combat", {})
    pre_battle_cfg = game_cfg.get("pre_battle", {})

    cognitive_loop = CognitiveLoop(
        llm=default_adapter,
        retrieval_top_k=combat_cfg.get("retrieval_top_k", 7),
        retrieval_decay=combat_cfg.get("retrieval_decay", 0.85),
        chat_max_rounds=combat_cfg.get("chat_max_rounds", 2),
        reflection_threshold=combat_cfg.get("reflection_threshold", 50.0),
        pre_battle_chat_max_rounds=pre_battle_cfg.get("chat_max_rounds", 4),
        chat_cooldown=combat_cfg.get("chat_cooldown", 3),
        embedding_cache=embedding_cache,
        routing=routing,
    )

    return cognitive_loop, model_id


# ==========================================================================
# Pre-battle social phase
# ==========================================================================


def run_pre_battle(
    env: Environment,
    cognitive_loop,
    pre_battle_cfg: dict,
) -> None:
    """Run the pre-battle social phase: 6 simultaneous ticks.

    During this phase:
    - All agents act simultaneously each tick
    - Primary action: MOVE or WAIT
    - Free CHAT: optional, can combine with primary action (no cost)
    - Perception radius is larger (default 12)
    - Chat exchanges are longer (default 4 rounds)
    - Memories and social models persist into combat
    """

    duration = pre_battle_cfg.get("duration_ticks", 6)
    pre_battle_radius = pre_battle_cfg.get("perception_radius", 12)

    # Switch to pre-battle perception radius
    original_radius = env.perception_engine.perception_radius
    env.perception_engine.perception_radius = pre_battle_radius

    map_name = pre_battle_cfg.get("map", "arena")
    location = "The Tavern" if map_name == "tavern" else "Arena"

    log.info(f"\n{'=' * 60}")
    log.info(f"PRE-BATTLE SOCIAL PHASE  —  {duration} ticks")
    log.info(f"  Location: {location} ({env.grid.width}x{env.grid.height})")
    log.info(f"  Perception radius: {pre_battle_radius}")
    log.info(f"  Chat max rounds: {pre_battle_cfg.get('chat_max_rounds', 4)}")
    log.info(f"{'=' * 60}")

    agents = env.alive_agents()

    for tick in range(1, duration + 1):
        log.info(f"\n--- Social Tick {tick}/{duration} ---")
        print_grid(env)

        # All agents decide simultaneously
        decisions = cognitive_loop.run_pre_battle_tick(
            agents=agents,
            env=env,
            tick_number=tick,
            total_ticks=duration,
        )

        # Track which agents have already been engaged in dialogue this tick
        # to avoid duplicate conversations (A chats B AND B chats A)
        chatted_pairs: set[frozenset[str]] = set()

        # Resolve all compound decisions (primary action + optional free chat)
        for agent, decision in decisions:
            # 1. Resolve primary action (MOVE or WAIT)
            primary = decision.primary_action
            if primary.action_type == ActionType.MOVE:
                result = env.resolve_action(primary)
                log.info(f"  [{agent.name}] {result.description}")
            elif primary.action_type == ActionType.WAIT:
                log.info(
                    f"  [{agent.name}] waits and observes. "
                    f"({primary.reasoning or 'no reason given'})"
                )

            # 2. Resolve optional free chat
            chat = decision.chat_action
            if chat and chat.target_agent:
                pair = frozenset({agent.agent_id, chat.target_agent})
                if pair not in chatted_pairs:
                    chatted_pairs.add(pair)
                    cognitive_loop.handle_pre_battle_chat(
                        initiator=agent,
                        action=chat,
                        env=env,
                        tick_number=tick,
                    )
                else:
                    target_name = env.agents.get(chat.target_agent)
                    target_label = (
                        target_name.name if target_name else chat.target_agent
                    )
                    log.info(
                        f"  [{agent.name}] wanted to chat with "
                        f"{target_label} but they already talked this tick"
                    )

        # Clear recent actions for next tick's perceptions
        env.recent_actions.clear()

    # Restore combat perception radius
    env.perception_engine.perception_radius = original_radius

    log.info(f"\n{'=' * 60}")
    log.info("PRE-BATTLE PHASE COMPLETE")
    log.info(f"{'=' * 60}")
    print_social_stats(env)


# ==========================================================================
# Battle loop
# ==========================================================================


def run_battle(
    env: Environment,
    use_llm: bool = True,
    cognitive_loop=None,
    model_id: str = "",
) -> Agent | None:
    """Run the combat loop until a winner emerges or max rounds exceeded.

    If cognitive_loop is provided (from pre-battle), reuse it so that
    memories and social models carry over.
    """
    from cognition.cognitive_loop import CognitiveLoop

    max_rounds = 50

    if use_llm and cognitive_loop is None:
        # Set up fresh cognitive loop (no pre-battle)
        game_cfg = load_game_config()
        cognitive_loop, model_id = setup_cognitive_loop(game_cfg)

        for agent in env.agents.values():
            cognitive_loop.register(agent)

        log.info(f"\nCognitive loop initialised (model: {model_id})")

    elif use_llm and cognitive_loop is not None:
        log.info(f"\nCognitive loop carried from pre-battle (model: {model_id})")
        # Reset the planner's plans so agents generate fresh combat plans
        # (social plans won't apply to combat)
        cognitive_loop._planner._plans.clear()

    # Stagnation tracking
    game_cfg = load_game_config()
    combat_cfg = game_cfg.get("combat", {})
    max_no_damage_rounds = combat_cfg.get("max_no_damage_rounds", 4)
    rounds_without_damage = 0
    last_damage_round = 0
    damage_this_round = False

    order = env.start_combat()
    log.info(f"\n{'=' * 60}")
    log.info(f"COMBAT BEGINS  —  Initiative: {', '.join(order)}")
    if use_llm:
        log.info("  Mode: LLM-driven (Phase 4 — Full: Pre-Battle + Combat)")
    else:
        log.info("  Mode: Random actions (Phase 1)")
    log.info(f"{'=' * 60}")

    while not env.is_combat_over() and env.turn_manager.round_number <= max_rounds:
        current = env.current_agent()
        if current is None or not current.is_alive:
            next_agent = env.advance_turn()
            if next_agent is None:
                break
            continue

        round_num = env.turn_manager.round_number

        # Print round header on first agent of each round
        if env.turn_manager._current_idx == 0:
            # End-of-round processing (mana regen, stagnation tracking)
            if round_num > 1:
                if not damage_this_round:
                    rounds_without_damage += 1
                else:
                    rounds_without_damage = 0
                damage_this_round = False

                # End-of-round mana regen for all living agents
                for a in env.alive_agents():
                    restored = a.attributes.regen_mana()
                    if restored > 0:
                        log.debug(f"  {a.name} regenerated {restored} mana")

                # End-of-round cooldown tick for all living agents
                for a in env.alive_agents():
                    a.attributes.tick_cooldowns()

                # End-of-round DoT tick for all living agents
                for a in list(env.alive_agents()):
                    for eff in a.attributes.status_effects:
                        if get_behavior(eff.get("type", "")) == "damage_over_time":
                            mag = eff.get("magnitude", 0)
                            dot_dmg = int(mag * a.attributes.max_hp)
                            if dot_dmg > 0:
                                a.attributes.take_damage(dot_dmg)
                                log.info(
                                    f"  {a.name} takes {dot_dmg} {eff.get('type', 'DoT')} damage!"
                                )
                                damage_this_round = True
                                if not a.is_alive:
                                    dot_type = eff.get("type", "DoT")
                                    dot_source = eff.get("source", "unknown")
                                    killer_name = (
                                        env.agents[dot_source].name
                                        if dot_source in env.agents
                                        else dot_source
                                    )
                                    env.handle_agent_death(
                                        a.agent_id,
                                        killer=killer_name,
                                        method=f"{dot_type} damage",
                                        round_num=round_num,
                                    )
                                    if cognitive_loop is not None:
                                        cognitive_loop.broadcast_death(
                                            dead_agent=a,
                                            killer_name=killer_name,
                                            method=f"{dot_type} damage",
                                            round_num=round_num,
                                            env=env,
                                        )
                                    log.info(
                                        f"  {a.name} has been killed by {dot_type}!"
                                    )
                                    break  # agent is dead, no more DoT processing

                # End-of-round bonus actions for fast agents (spd >= 15)
                if cognitive_loop is not None and not env.is_combat_over():
                    for a in list(env.alive_agents()):
                        if a.attributes.spd >= 15:
                            chance = 10 + (a.attributes.spd - 15) * 2
                            if random.random() * 100 < chance:
                                log.info(
                                    f"  *** {a.name}'s speed grants a BONUS ACTION! ***"
                                )
                                bonus_decision = cognitive_loop.run_bonus_turn(
                                    a, env, round_num - 1
                                )
                                bonus_result = env.resolve_action(
                                    bonus_decision.primary_action
                                )
                                log.info(f"  [BONUS] {bonus_result.description}")
                                _broadcast_kills(
                                    bonus_result, a, env, round_num - 1, cognitive_loop
                                )
                                if bonus_result.success and (
                                    bonus_decision.primary_action.action_type
                                    == ActionType.ATTACK
                                ):
                                    damage_this_round = True
                                # Handle optional bonus chat
                                if (
                                    bonus_decision.chat_action
                                    and bonus_decision.chat_action.target_agent
                                ):
                                    if cognitive_loop.can_chat_combat(
                                        a.agent_id, round_num - 1
                                    ):
                                        cognitive_loop._handle_chat(
                                            a,
                                            bonus_decision.chat_action,
                                            env,
                                            round_num - 1,
                                        )
                                        cognitive_loop.record_chat(
                                            a.agent_id, round_num - 1
                                        )
                                if env.is_combat_over():
                                    break

            log.info(f"\n--- Round {round_num} ---")
            if rounds_without_damage >= max_no_damage_rounds:
                log.info(
                    f"  *** STAGNATION WARNING: {rounds_without_damage} rounds "
                    f"with no damage dealt! ***"
                )
            print_grid(env)
            print_status(env)

        # Build urgency text for stagnation
        urgency_text = ""
        if rounds_without_damage >= max_no_damage_rounds:
            urgency_text = (
                f"No damage has been dealt for {rounds_without_damage} rounds! "
                f"The arena grows impatient. You MUST attack an enemy THIS TURN "
                f"or close distance aggressively. Inaction means death."
            )

        # Tick status effects at start of agent's turn
        expired = current.attributes.tick_status_effects()
        for eff in expired:
            env.world_state.remove_status(
                current.agent_id, eff if eff != "defend" else "defending"
            )

        # Skip-turn check: if agent has a skip_turn status, they lose their turn
        skip = False
        for eff in current.attributes.status_effects:
            if get_behavior(eff.get("type", "")) == "skip_turn":
                skip = True
                break
        if skip:
            log.info(f"  [{current.name}] is stunned and loses their turn!")
            env.advance_turn()
            continue

        # Pick action: cognitive loop or random fallback
        if cognitive_loop is not None:
            decision = cognitive_loop.run_turn(
                current, env, round_num, urgency_text=urgency_text
            )

            # Resolve primary action
            result = env.resolve_action(decision.primary_action)
            log.info(f"  {result.description}")
            _broadcast_kills(result, current, env, round_num, cognitive_loop)

            # Track damage
            if result.success and (
                decision.primary_action.action_type == ActionType.ATTACK
                or (
                    decision.primary_action.action_type == ActionType.ABILITY
                    and result.details.get("damage", 0) > 0
                )
            ):
                damage_this_round = True

            # Handle optional free chat (only for non-attack primaries)
            if decision.chat_action and decision.chat_action.target_agent:
                if cognitive_loop.can_chat_combat(current.agent_id, round_num):
                    cognitive_loop._handle_chat(
                        current, decision.chat_action, env, round_num
                    )
                    cognitive_loop.record_chat(current.agent_id, round_num)
                else:
                    log.info(f"  [{current.name}] wanted to chat but is on cooldown")
        else:
            action = pick_random_action(current, env)
            result = env.resolve_action(action)
            log.info(f"  {result.description}")
            _broadcast_kills(result, current, env, round_num, cognitive_loop)
            if result.success and action.action_type == ActionType.ATTACK:
                damage_this_round = True

        # Advance to next agent
        env.advance_turn()

    winner = env.get_winner()
    winners = env.get_winners()
    log.info(f"\n{'=' * 60}")
    if len(winners) > 1:
        names = ", ".join(w.name for w in winners)
        log.info(f"ALLIANCE VICTORY: {names} win together!")
    elif winner:
        log.info(f"VICTORY: {winner.name} wins!")
    else:
        log.info("DRAW: No clear winner.")
    log.info(f"{'=' * 60}")
    print_status(env)

    # Print memory stats if cognitive loop was used
    if cognitive_loop is not None:
        log.info(f"\n--- Memory Stats ---")
        for agent in env.agents.values():
            state = cognitive_loop.get_state(agent.agent_id)
            if state:
                log.info(
                    f"  {agent.name}: {len(state.memory)} memories "
                    f"(importance acc: {state.memory.importance_accumulator:.0f})"
                )

        print_social_stats(env)

    return winner


# ==========================================================================
# Async variants (pre-battle + combat)
# ==========================================================================


async def async_run_pre_battle(
    env: Environment,
    cognitive_loop,
    pre_battle_cfg: dict,
) -> None:
    """Async version of run_pre_battle(). All agents run concurrently each tick."""

    duration = pre_battle_cfg.get("duration_ticks", 6)
    pre_battle_radius = pre_battle_cfg.get("perception_radius", 12)

    original_radius = env.perception_engine.perception_radius
    env.perception_engine.perception_radius = pre_battle_radius

    map_name = pre_battle_cfg.get("map", "arena")
    location = "The Tavern" if map_name == "tavern" else "Arena"

    log.info(f"\n{'=' * 60}")
    log.info(f"PRE-BATTLE SOCIAL PHASE (async)  —  {duration} ticks")
    log.info(f"  Location: {location} ({env.grid.width}x{env.grid.height})")
    log.info(f"  Perception radius: {pre_battle_radius}")
    log.info(f"  Chat max rounds: {pre_battle_cfg.get('chat_max_rounds', 4)}")
    log.info(f"{'=' * 60}")

    agents = env.alive_agents()

    for tick in range(1, duration + 1):
        log.info(f"\n--- Social Tick {tick}/{duration} ---")
        print_grid(env)

        # All agents decide concurrently
        decisions = await cognitive_loop.async_run_pre_battle_tick(
            agents=agents,
            env=env,
            tick_number=tick,
            total_ticks=duration,
        )

        chatted_pairs: set[frozenset[str]] = set()

        for agent, decision in decisions:
            primary = decision.primary_action
            if primary.action_type == ActionType.MOVE:
                result = env.resolve_action(primary)
                log.info(f"  [{agent.name}] {result.description}")
            elif primary.action_type == ActionType.WAIT:
                log.info(
                    f"  [{agent.name}] waits and observes. "
                    f"({primary.reasoning or 'no reason given'})"
                )

            chat = decision.chat_action
            if chat and chat.target_agent:
                pair = frozenset({agent.agent_id, chat.target_agent})
                if pair not in chatted_pairs:
                    chatted_pairs.add(pair)
                    cognitive_loop.handle_pre_battle_chat(
                        initiator=agent,
                        action=chat,
                        env=env,
                        tick_number=tick,
                    )
                else:
                    target_name = env.agents.get(chat.target_agent)
                    target_label = (
                        target_name.name if target_name else chat.target_agent
                    )
                    log.info(
                        f"  [{agent.name}] wanted to chat with "
                        f"{target_label} but they already talked this tick"
                    )

        env.recent_actions.clear()

    env.perception_engine.perception_radius = original_radius

    log.info(f"\n{'=' * 60}")
    log.info("PRE-BATTLE PHASE COMPLETE")
    log.info(f"{'=' * 60}")
    print_social_stats(env)


async def async_run_battle(
    env: Environment,
    cognitive_loop,
    model_id: str = "",
) -> Agent | None:
    """Async version of run_battle(). Uses async_run_turn for LLM calls."""
    max_rounds = 50

    log.info(f"\nCognitive loop carried from pre-battle (model: {model_id})")
    cognitive_loop._planner._plans.clear()

    game_cfg = load_game_config()
    combat_cfg = game_cfg.get("combat", {})
    max_no_damage_rounds = combat_cfg.get("max_no_damage_rounds", 4)
    rounds_without_damage = 0
    damage_this_round = False

    order = env.start_combat()
    log.info(f"\n{'=' * 60}")
    log.info(f"COMBAT BEGINS (async)  —  Initiative: {', '.join(order)}")
    log.info("  Mode: LLM-driven (Phase 4 — Full: Pre-Battle + Combat)")
    log.info(f"{'=' * 60}")

    while not env.is_combat_over() and env.turn_manager.round_number <= max_rounds:
        current = env.current_agent()
        if current is None or not current.is_alive:
            next_agent = env.advance_turn()
            if next_agent is None:
                break
            continue

        round_num = env.turn_manager.round_number

        if env.turn_manager._current_idx == 0:
            if round_num > 1:
                if not damage_this_round:
                    rounds_without_damage += 1
                else:
                    rounds_without_damage = 0
                damage_this_round = False

                for a in env.alive_agents():
                    restored = a.attributes.regen_mana()
                    if restored > 0:
                        log.debug(f"  {a.name} regenerated {restored} mana")

                # End-of-round cooldown tick for all living agents
                for a in env.alive_agents():
                    a.attributes.tick_cooldowns()

                # End-of-round DoT tick for all living agents
                for a in list(env.alive_agents()):
                    for eff in a.attributes.status_effects:
                        if get_behavior(eff.get("type", "")) == "damage_over_time":
                            mag = eff.get("magnitude", 0)
                            dot_dmg = int(mag * a.attributes.max_hp)
                            if dot_dmg > 0:
                                a.attributes.take_damage(dot_dmg)
                                log.info(
                                    f"  {a.name} takes {dot_dmg} {eff.get('type', 'DoT')} damage!"
                                )
                                damage_this_round = True
                                if not a.is_alive:
                                    dot_type = eff.get("type", "DoT")
                                    dot_source = eff.get("source", "unknown")
                                    killer_name = (
                                        env.agents[dot_source].name
                                        if dot_source in env.agents
                                        else dot_source
                                    )
                                    env.handle_agent_death(
                                        a.agent_id,
                                        killer=killer_name,
                                        method=f"{dot_type} damage",
                                        round_num=round_num,
                                    )
                                    cognitive_loop.broadcast_death(
                                        dead_agent=a,
                                        killer_name=killer_name,
                                        method=f"{dot_type} damage",
                                        round_num=round_num,
                                        env=env,
                                    )
                                    log.info(
                                        f"  {a.name} has been killed by {dot_type}!"
                                    )
                                    break  # agent is dead, no more DoT processing

                # End-of-round bonus actions for fast agents (spd >= 15)
                if not env.is_combat_over():
                    for a in list(env.alive_agents()):
                        if a.attributes.spd >= 15:
                            chance = 10 + (a.attributes.spd - 15) * 2
                            if random.random() * 100 < chance:
                                log.info(
                                    f"  *** {a.name}'s speed grants a BONUS ACTION! ***"
                                )
                                bonus_decision = (
                                    await cognitive_loop.async_run_bonus_turn(
                                        a, env, round_num - 1
                                    )
                                )
                                bonus_result = env.resolve_action(
                                    bonus_decision.primary_action
                                )
                                log.info(f"  [BONUS] {bonus_result.description}")
                                _broadcast_kills(
                                    bonus_result,
                                    a,
                                    env,
                                    round_num - 1,
                                    cognitive_loop,
                                )
                                if bonus_result.success and (
                                    bonus_decision.primary_action.action_type
                                    == ActionType.ATTACK
                                ):
                                    damage_this_round = True
                                # Handle optional bonus chat
                                if (
                                    bonus_decision.chat_action
                                    and bonus_decision.chat_action.target_agent
                                ):
                                    if cognitive_loop.can_chat_combat(
                                        a.agent_id, round_num - 1
                                    ):
                                        cognitive_loop._handle_chat(
                                            a,
                                            bonus_decision.chat_action,
                                            env,
                                            round_num - 1,
                                        )
                                        cognitive_loop.record_chat(
                                            a.agent_id, round_num - 1
                                        )
                                if env.is_combat_over():
                                    break

            log.info(f"\n--- Round {round_num} ---")
            if rounds_without_damage >= max_no_damage_rounds:
                log.info(
                    f"  *** STAGNATION WARNING: {rounds_without_damage} rounds "
                    f"with no damage dealt! ***"
                )
            print_grid(env)
            print_status(env)

        urgency_text = ""
        if rounds_without_damage >= max_no_damage_rounds:
            urgency_text = (
                f"No damage has been dealt for {rounds_without_damage} rounds! "
                f"The arena grows impatient. You MUST attack an enemy THIS TURN "
                f"or close distance aggressively. Inaction means death."
            )

        expired = current.attributes.tick_status_effects()
        for eff in expired:
            env.world_state.remove_status(
                current.agent_id, eff if eff != "defend" else "defending"
            )

        # Skip-turn check: if agent has a skip_turn status, they lose their turn
        skip = False
        for eff in current.attributes.status_effects:
            if get_behavior(eff.get("type", "")) == "skip_turn":
                skip = True
                break
        if skip:
            log.info(f"  [{current.name}] is stunned and loses their turn!")
            env.advance_turn()
            continue

        decision = await cognitive_loop.async_run_turn(
            current, env, round_num, urgency_text=urgency_text
        )

        result = env.resolve_action(decision.primary_action)
        log.info(f"  {result.description}")
        _broadcast_kills(result, current, env, round_num, cognitive_loop)

        if result.success and (
            decision.primary_action.action_type == ActionType.ATTACK
            or (
                decision.primary_action.action_type == ActionType.ABILITY
                and result.details.get("damage", 0) > 0
            )
        ):
            damage_this_round = True

        if decision.chat_action and decision.chat_action.target_agent:
            if cognitive_loop.can_chat_combat(current.agent_id, round_num):
                cognitive_loop._handle_chat(
                    current, decision.chat_action, env, round_num
                )
                cognitive_loop.record_chat(current.agent_id, round_num)
            else:
                log.info(f"  [{current.name}] wanted to chat but is on cooldown")

        env.advance_turn()

    winner = env.get_winner()
    winners = env.get_winners()
    log.info(f"\n{'=' * 60}")
    if len(winners) > 1:
        names = ", ".join(w.name for w in winners)
        log.info(f"ALLIANCE VICTORY: {names} win together!")
    elif winner:
        log.info(f"VICTORY: {winner.name} wins!")
    else:
        log.info("DRAW: No clear winner.")
    log.info(f"{'=' * 60}")
    print_status(env)

    log.info(f"\n--- Memory Stats ---")
    for agent in env.agents.values():
        state = cognitive_loop.get_state(agent.agent_id)
        if state:
            log.info(
                f"  {agent.name}: {len(state.memory)} memories "
                f"(importance acc: {state.memory.importance_accumulator:.0f})"
            )

    print_social_stats(env)
    return winner


async def _async_main(
    game_cfg: dict,
    combat_env: Environment,
    tavern_env: Environment | None,
    agents: list[Agent],
    pre_battle_enabled: bool,
    pre_battle_cfg: dict,
) -> None:
    """Async main — runs pre-battle and combat with async concurrency."""
    # Determine which env to register agents on initially
    initial_env = tavern_env if tavern_env is not None else combat_env

    cognitive_loop, model_id = setup_cognitive_loop(game_cfg)
    for agent in initial_env.agents.values():
        cognitive_loop.register(agent)
    log.info(f"\nCognitive loop initialised (model: {model_id})")

    if pre_battle_enabled:
        await async_run_pre_battle(initial_env, cognitive_loop, pre_battle_cfg)

    # If we used a tavern, transition agents to the combat arena
    if tavern_env is not None:
        log.info("\n" + "=" * 60)
        log.info("Agents leave the tavern and enter the combat arena...")
        log.info("=" * 60)
        log.info("\nPlacing agents on combat grid:")
        place_agents(agents, combat_env)
        print_grid(combat_env)

    await async_run_battle(combat_env, cognitive_loop, model_id)


# ==========================================================================
# Character generation
# ==========================================================================


def _run_generate(args: argparse.Namespace) -> None:
    """Interactive character generation via LLM."""
    from character_generator import generate_character, save_character, to_yaml
    from llm.openrouter_adapter import OpenRouterAdapter

    print("=== Battle-Agents Character Generator ===\n")

    # Use CLI args if provided, otherwise prompt interactively.
    name = args.name
    description = args.desc

    if not name:
        try:
            name = input("Character name: ").strip()
        except EOFError:
            print("Error: no input available. Use --name and --desc flags.")
            sys.exit(1)
    if not name:
        print("Error: name cannot be empty.")
        sys.exit(1)

    if not description:
        try:
            description = input(
                "Description (fighting style, personality, etc.): "
            ).strip()
        except EOFError:
            print("Error: no input available. Use --name and --desc flags.")
            sys.exit(1)
    if not description:
        print("Error: description cannot be empty.")
        sys.exit(1)

    # Set up LLM adapter (lightweight — no full cognitive loop needed).
    llm_cfg = load_llm_config()
    adapters_cfg = llm_cfg.get("adapters", {})
    or_cfg = adapters_cfg.get("openrouter", {})
    models_cfg = or_cfg.get("models", {})
    model_id = "google/gemini-2.5-flash"
    for _name, mcfg in models_cfg.items():
        model_id = mcfg.get("model_id", model_id)
        break
    adapter = OpenRouterAdapter(model=model_id)

    print(f"\nGenerating character with {model_id}...\n")

    data = generate_character(name, description, adapter)
    yaml_str = to_yaml(data)

    print("--- Generated Character YAML ---")
    print(yaml_str)

    if args.save:
        path = save_character(data)
        print(f"Saved to {path}")


# ==========================================================================
# Entry point
# ==========================================================================


def main() -> None:
    parser = argparse.ArgumentParser(description="Battle-Agents combat simulation")
    parser.add_argument(
        "--random",
        action="store_true",
        help="Use random actions (Phase 1 mode) instead of LLM",
    )
    parser.add_argument(
        "--no-social",
        action="store_true",
        help="Skip the pre-battle social phase (LLM combat only)",
    )
    parser.add_argument(
        "--chars",
        type=int,
        default=3,
        help="Number of characters to use (default: 3)",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate a new character via LLM (interactive, prints YAML)",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Character name (use with --generate to skip interactive prompt)",
    )
    parser.add_argument(
        "--desc",
        type=str,
        default=None,
        help="Character description (use with --generate to skip interactive prompt)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save the generated character to config/characters/ (use with --generate)",
    )
    parser.add_argument(
        "--battle",
        action="store_true",
        help="After generating, run a full battle with all characters (implies --save)",
    )
    args = parser.parse_args()

    # --save and --battle only make sense with --generate
    if args.save and not args.generate:
        parser.error("--save requires --generate")
    if args.battle and not args.generate:
        parser.error("--battle requires --generate")
    if (args.name or args.desc) and not args.generate:
        parser.error("--name and --desc require --generate")

    # --generate and --random are mutually exclusive
    if args.generate and args.random:
        parser.error("--generate and --random are mutually exclusive")

    # --battle implies --save (character must be on disk for the battle loader)
    if args.battle:
        args.save = True

    # --- Character generation mode ---
    if args.generate:
        _run_generate(args)
        if not args.battle:
            return
        # Fall through to normal battle setup — the generated character
        # is already saved to config/characters/ and will be picked up
        # by load_all_characters() below.
        log.info("\n" + "=" * 60)
        log.info("Continuing to battle with all characters...")
        log.info("=" * 60)

    use_llm = not args.random
    skip_social = args.random or args.no_social

    if args.random:
        mode_label = "Phase 1: Random Combat"
    elif args.no_social:
        mode_label = "Phase 4: LLM-Driven Combat (no pre-battle)"
    else:
        mode_label = "Phase 4: Full Simulation (Pre-Battle Social + Combat)"
    log.info(f"Battle-Agents — {mode_label}")
    log.info("=" * 60)

    # Load config
    game_cfg = load_game_config()
    load_balance_config(game_cfg)  # initialise BalanceConfig for Attributes
    grid_cfg = game_cfg.get("grid", {})
    combat_cfg = game_cfg.get("combat", {})
    pre_battle_cfg = game_cfg.get("pre_battle", {})
    pre_battle_enabled = pre_battle_cfg.get("enabled", False) and not skip_social

    # Build combat grid + environment
    victory_cfg = game_cfg.get("victory", {})
    victory_mode = victory_cfg.get("mode", "last_standing")
    combat_grid = BattleGrid.create_arena(
        width=grid_cfg.get("width", 12),
        height=grid_cfg.get("height", 10),
    )
    combat_env = Environment(
        grid=combat_grid,
        perception_radius=combat_cfg.get("perception_radius", 8),
        victory_mode=victory_mode,
    )

    # Load characters
    agents = load_all_characters()
    if args.chars and args.chars < len(agents):
        agents = agents[: args.chars]
    log.info(f"\nLoaded {len(agents)} agents:")
    for a in agents:
        log.info(f"  {a.status_summary()}")

    # Determine pre-battle map
    pre_battle_map = pre_battle_cfg.get("map", "arena")
    use_tavern = pre_battle_enabled and pre_battle_map == "tavern"

    if use_tavern:
        # Tavern map for pre-battle social phase
        tavern_grid = BattleGrid.create_tavern()
        tavern_env = Environment(
            grid=tavern_grid,
            perception_radius=pre_battle_cfg.get("perception_radius", 12),
            victory_mode=victory_mode,
        )
        log.info("\nPlacing agents in the tavern:")
        place_agents(agents, tavern_env, min_dist=2)
    else:
        tavern_env = None

    if not use_tavern:
        # Place agents directly on the combat grid
        log.info("\nPlacing agents on grid:")
        place_agents(agents, combat_env)

    if use_llm:
        # Async path — all LLM calls use asyncio concurrency
        asyncio.run(
            _async_main(
                game_cfg=game_cfg,
                combat_env=combat_env,
                tavern_env=tavern_env,
                agents=agents,
                pre_battle_enabled=pre_battle_enabled,
                pre_battle_cfg=pre_battle_cfg,
            )
        )
    else:
        # Random mode — fully sync, no LLM needed
        if not use_tavern:
            log.info("\nSkipping pre-battle phase (random mode)")
        else:
            # Even in random mode, place on combat grid
            log.info("\nPlacing agents on combat grid:")
            place_agents(agents, combat_env)
        run_battle(combat_env, use_llm=False)


if __name__ == "__main__":
    main()
