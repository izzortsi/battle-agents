"""Battle-Agents runner — main entry point.

Phase 2: LLM-driven combat via the cognitive loop.
Agents perceive, remember, retrieve, and decide using an LLM.

Usage:
    python runner.py             # LLM-driven combat (default)
    python runner.py --random    # Phase 1 random-action fallback
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
from config_loader import load_all_characters, load_game_config, load_llm_config
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


# ==========================================================================
# Battle loop
# ==========================================================================


def run_battle(
    env: Environment,
    use_llm: bool = True,
) -> Agent | None:
    """Run the combat loop until a winner emerges or max rounds exceeded."""
    from cognition.cognitive_loop import CognitiveLoop
    from llm.adapter import ModelRegistry
    from llm.openrouter_adapter import OpenRouterAdapter

    max_rounds = 50

    # Set up LLM-driven cognitive loop if enabled
    cognitive_loop: CognitiveLoop | None = None
    if use_llm:
        llm_cfg = load_llm_config()
        # Build the adapter from config
        adapters_cfg = llm_cfg.get("adapters", {})
        or_cfg = adapters_cfg.get("openrouter", {})
        models_cfg = or_cfg.get("models", {})

        # Find the first model config (or use defaults)
        model_id = "google/gemini-2.5-flash"
        for _name, mcfg in models_cfg.items():
            model_id = mcfg.get("model_id", model_id)
            break

        adapter = OpenRouterAdapter(model=model_id)
        registry = ModelRegistry()
        registry.register(llm_cfg.get("default_adapter", "openrouter"), adapter)

        # Read retrieval config from game_config
        game_cfg = load_game_config()
        combat_cfg = game_cfg.get("combat", {})

        cognitive_loop = CognitiveLoop(
            llm=adapter,
            retrieval_top_k=combat_cfg.get("retrieval_top_k", 7),
            retrieval_decay=combat_cfg.get("retrieval_decay", 0.85),
            chat_max_rounds=combat_cfg.get("chat_max_rounds", 2),
            reflection_threshold=combat_cfg.get("reflection_threshold", 50.0),
        )

        # Register all agents
        for agent in env.agents.values():
            cognitive_loop.register(agent)

        log.info(f"\nCognitive loop initialised (model: {model_id})")

    order = env.start_combat()
    log.info(f"\n{'=' * 60}")
    log.info(f"COMBAT BEGINS  —  Initiative: {', '.join(order)}")
    if use_llm:
        log.info(
            "  Mode: LLM-driven (Phase 3 — Dialogue, Social, Reflection, Planning)"
        )
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
            log.info(f"\n--- Round {round_num} ---")
            print_grid(env)
            print_status(env)

        # Tick status effects at start of agent's turn
        expired = current.attributes.tick_status_effects()
        for eff in expired:
            env.world_state.remove_status(
                current.agent_id, eff if eff != "defend" else "defending"
            )

        # Pick action: cognitive loop or random fallback
        if cognitive_loop is not None:
            action = cognitive_loop.run_turn(current, env, round_num)
        else:
            action = pick_random_action(current, env)

        result = env.resolve_action(action)
        log.info(f"  {result.description}")

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
    args = parser.parse_args()

    use_llm = not args.random
    mode_label = (
        "Phase 3: LLM-Driven Combat (Dialogue + Social + Reflection + Planning)"
        if use_llm
        else "Phase 1: Random Combat"
    )
    log.info(f"Battle-Agents — {mode_label}")
    log.info("=" * 60)

    # Load config
    game_cfg = load_game_config()
    grid_cfg = game_cfg.get("grid", {})
    combat_cfg = game_cfg.get("combat", {})

    # Build grid
    grid = BattleGrid(
        width=grid_cfg.get("width", 12),
        height=grid_cfg.get("height", 10),
    )

    # Build environment
    env = Environment(
        grid=grid,
        perception_radius=combat_cfg.get("perception_radius", 8),
    )

    # Load characters
    agents = load_all_characters()
    log.info(f"\nLoaded {len(agents)} agents:")
    for a in agents:
        log.info(f"  {a.status_summary()}")

    # Place agents
    log.info("\nPlacing agents on grid:")
    place_agents(agents, env)

    # Run battle
    run_battle(env, use_llm=use_llm)


if __name__ == "__main__":
    main()
