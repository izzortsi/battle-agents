"""Battle-Agents runner — main entry point.

Phase 4: Full two-phase simulation: pre-battle social phase → combat.
Agents perceive, remember, retrieve, reflect, plan, and decide using an LLM.
Memory and social models persist across both phases.

Usage:
    python runner.py             # LLM-driven (pre-battle + combat)
    python runner.py --random    # Phase 1 random-action fallback (combat only)
    python runner.py --no-social # LLM combat only, skip pre-battle
"""

from __future__ import annotations

import argparse
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
from config_loader import load_all_characters, load_balance_config, load_game_config, load_llm_config
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
# Grid display and agent placement
# ==========================================================================


def place_agents(agents: list[Agent], env: Environment) -> None:
    """Place agents on the grid in spread-out positions."""
    w, h = env.grid.width, env.grid.height
    positions = [
        (1, 1),
        (w - 2, 1),
        (1, h - 2),
        (w - 2, h - 2),
        (w // 2, 1),
        (w // 2, h - 2),
    ]
    for i, agent in enumerate(agents):
        x, y = positions[i % len(positions)]
        env.register_agent(agent, x, y)
        log.info(f"  Placed {agent.name} at ({x}, {y})")


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
            elif grid._tiles.get((x, y)) == BattleGrid.__class__:
                row += " #"
            else:
                row += " ."
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


def setup_cognitive_loop(game_cfg: dict) -> tuple:
    """Create and configure the LLM adapter and CognitiveLoop.

    Returns (cognitive_loop, model_id).
    """
    from cognition.cognitive_loop import CognitiveLoop
    from cognition.embeddings import create_embedding_cache
    from llm.adapter import ModelRegistry
    from llm.openrouter_adapter import OpenRouterAdapter

    llm_cfg = load_llm_config()
    adapters_cfg = llm_cfg.get("adapters", {})
    or_cfg = adapters_cfg.get("openrouter", {})
    models_cfg = or_cfg.get("models", {})

    model_id = "google/gemini-2.5-flash"
    for _name, mcfg in models_cfg.items():
        model_id = mcfg.get("model_id", model_id)
        break

    adapter = OpenRouterAdapter(model=model_id)
    registry = ModelRegistry()
    registry.register(llm_cfg.get("default_adapter", "openrouter"), adapter)

    # Create embedding cache from config (None if provider is "none")
    embedding_cfg = llm_cfg.get("embedding", {})
    embedding_cache = create_embedding_cache(embedding_cfg, llm_cfg)

    combat_cfg = game_cfg.get("combat", {})
    pre_battle_cfg = game_cfg.get("pre_battle", {})

    cognitive_loop = CognitiveLoop(
        llm=adapter,
        retrieval_top_k=combat_cfg.get("retrieval_top_k", 7),
        retrieval_decay=combat_cfg.get("retrieval_decay", 0.85),
        chat_max_rounds=combat_cfg.get("chat_max_rounds", 2),
        reflection_threshold=combat_cfg.get("reflection_threshold", 50.0),
        pre_battle_chat_max_rounds=pre_battle_cfg.get("chat_max_rounds", 4),
        chat_cooldown=combat_cfg.get("chat_cooldown", 3),
        embedding_cache=embedding_cache,
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

    log.info(f"\n{'=' * 60}")
    log.info(f"PRE-BATTLE SOCIAL PHASE  —  {duration} ticks")
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

        # Pick action: cognitive loop or random fallback
        if cognitive_loop is not None:
            decision = cognitive_loop.run_turn(
                current, env, round_num, urgency_text=urgency_text
            )

            # Resolve primary action
            result = env.resolve_action(decision.primary_action)
            log.info(f"  {result.description}")

            # Track damage
            if (
                result.success
                and decision.primary_action.action_type == ActionType.ATTACK
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
            if result.success and action.action_type == ActionType.ATTACK:
                damage_this_round = True

        # Advance to next agent
        env.advance_turn()

    winner = env.get_winner()
    log.info(f"\n{'=' * 60}")
    if winner:
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
    args = parser.parse_args()

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

    # Build grid
    grid = BattleGrid(
        width=grid_cfg.get("width", 12),
        height=grid_cfg.get("height", 10),
    )

    # Build environment (start with combat perception radius)
    env = Environment(
        grid=grid,
        perception_radius=combat_cfg.get("perception_radius", 8),
    )

    # Load characters
    agents = load_all_characters()
    if args.chars and args.chars < len(agents):
        agents = agents[: args.chars]
    log.info(f"\nLoaded {len(agents)} agents:")
    for a in agents:
        log.info(f"  {a.status_summary()}")

    # Place agents
    log.info("\nPlacing agents on grid:")
    place_agents(agents, env)

    # Set up cognitive loop if using LLM
    cognitive_loop = None
    model_id = ""
    if use_llm:
        cognitive_loop, model_id = setup_cognitive_loop(game_cfg)
        for agent in env.agents.values():
            cognitive_loop.register(agent)
        log.info(f"\nCognitive loop initialised (model: {model_id})")

    # Phase 1: Pre-battle social phase (if enabled)
    if pre_battle_enabled and cognitive_loop is not None:
        run_pre_battle(env, cognitive_loop, pre_battle_cfg)
    elif pre_battle_enabled and cognitive_loop is None:
        log.info("\nSkipping pre-battle phase (random mode)")

    # Phase 2: Combat
    run_battle(
        env,
        use_llm=use_llm,
        cognitive_loop=cognitive_loop,
        model_id=model_id,
    )


if __name__ == "__main__":
    main()
