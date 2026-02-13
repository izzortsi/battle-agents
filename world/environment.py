"""Environment controller — manages the WorldState, resolves actions, drives the game loop.

This is the central orchestrator.  Agents submit actions; the environment
validates and resolves them against the world state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ontology.schemas import create_store
from ontology.world_state import WorldState
from world.battle_grid import BattleGrid
from world.perception_engine import Observation, PerceptionEngine
from world.turn_manager import TurnManager

if TYPE_CHECKING:
    from agent.agent import Agent
    from combat.actions import CombatAction

log = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """Result of resolving a single combat action."""

    agent_id: str
    success: bool
    description: str
    details: dict = field(default_factory=dict)


class Environment:
    """Top-level controller for the simulation."""

    def __init__(
        self,
        grid: BattleGrid,
        perception_radius: int = 8,
    ) -> None:
        self.grid = grid
        self.world_state = WorldState(create_store())
        self.turn_manager = TurnManager()
        self.perception_engine = PerceptionEngine(
            self.world_state, grid, perception_radius
        )
        self.agents: dict[str, Agent] = {}
        self.recent_actions: dict[str, dict] = {}  # last tick's action descriptions
        self.event_log: list[ActionResult] = []

    # -- Setup -----------------------------------------------------------------

    def register_agent(self, agent: Agent, x: int, y: int) -> None:
        self.agents[agent.agent_id] = agent
        tile = BattleGrid.tile_key(x, y)
        self.world_state.set_position(agent.agent_id, tile)

    def start_combat(self) -> list[str]:
        """Roll initiative and begin combat."""
        alive = [a for a in self.agents.values() if a.is_alive]
        order = self.turn_manager.roll_initiative(alive)
        log.info(f"Initiative order: {order}")
        return order

    # -- Perception ------------------------------------------------------------

    def get_perceptions(self, agent: Agent) -> list[Observation]:
        all_agents = list(self.agents.values())
        return self.perception_engine.perceive(agent, all_agents, self.recent_actions)

    def get_perception_text(self, agent: Agent) -> str:
        obs = self.get_perceptions(agent)
        return self.perception_engine.format_perception_text(agent, obs)

    # -- Action resolution -----------------------------------------------------

    def resolve_action(self, action: CombatAction) -> ActionResult:
        """Resolve a combat action against the world state.

        Delegates to combat.action_resolver (imported here to avoid circular deps).
        After resolution, updates social models for combat events.
        """
        from combat.action_resolver import resolve

        result = resolve(action, self)
        self.event_log.append(result)

        # Store for next tick's perceptions
        self.recent_actions[action.agent_id] = {
            "action_type": action.action_type.value,
            "description": result.description,
            "success": result.success,
            **result.details,
        }

        # Post-resolution social model updates
        if result.success:
            self._update_social_models(action, result)

        return result

    def _update_social_models(self, action: CombatAction, result: ActionResult) -> None:
        """Update social models based on resolved combat events."""
        from combat.actions import ActionType

        turn = self.turn_manager.global_turn

        if action.action_type == ActionType.ATTACK and action.target_agent:
            attacker = self.agents.get(action.agent_id)
            target = self.agents.get(action.target_agent)
            if not attacker or not target:
                return

            damage = result.details.get("damage", 0)
            killed = result.details.get("killed", False)

            # Target's social model: attacked by attacker
            target.social.on_attacked_by(
                attacker_id=attacker.agent_id,
                turn=turn,
                damage=damage,
                agent_name=attacker.name,
            )

            # All other alive agents react based on their relationships
            for observer in self.alive_agents():
                if observer.agent_id in (attacker.agent_id, target.agent_id):
                    continue

                # If the observer considers the target an ally
                obs_disp_target = observer.social.get_disposition(target.agent_id)
                obs_disp_attacker = observer.social.get_disposition(attacker.agent_id)

                if killed:
                    if obs_disp_target > 0.15:
                        # Target was friendly/allied — negative toward killer
                        observer.social.on_ally_killed(
                            killer_id=attacker.agent_id,
                            ally_id=target.agent_id,
                            turn=turn,
                            agent_name=attacker.name,
                        )
                    elif obs_disp_target < -0.15:
                        # Target was an enemy — positive toward killer
                        observer.social.on_enemy_killed(
                            killer_id=attacker.agent_id,
                            enemy_id=target.agent_id,
                            turn=turn,
                            agent_name=attacker.name,
                        )
                elif obs_disp_target > 0.15:
                    # Observer saw an ally get attacked
                    observer.social.on_attacked_ally(
                        attacker_id=attacker.agent_id,
                        ally_id=target.agent_id,
                        turn=turn,
                        agent_name=attacker.name,
                    )

    # -- Game state queries ----------------------------------------------------

    def alive_agents(self) -> list[Agent]:
        return [a for a in self.agents.values() if a.is_alive]

    def is_combat_over(self) -> bool:
        alive = self.alive_agents()
        return len(alive) <= 1

    def get_winner(self) -> Agent | None:
        alive = self.alive_agents()
        return alive[0] if len(alive) == 1 else None

    # -- Turn management -------------------------------------------------------

    def current_agent(self) -> Agent | None:
        aid = self.turn_manager.current_agent_id
        if aid is None:
            return None
        return self.agents.get(aid)

    def advance_turn(self) -> Agent | None:
        """Advance to next alive agent.  Skips dead agents."""
        for _ in range(len(self.turn_manager.turn_order) + 1):
            aid = self.turn_manager.advance()
            if aid is None:
                return None
            agent = self.agents.get(aid)
            if agent and agent.is_alive:
                return agent
        return None

    def handle_agent_death(self, agent_id: str) -> None:
        self.turn_manager.remove_agent(agent_id)
        log.info(f"{agent_id} has been eliminated.")
