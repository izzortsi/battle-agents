"""Perception engine — spatial filtering of world state into per-agent observations.

Each turn, produces a list of observation dicts for the active agent, containing
only what they can perceive (entities within perception radius).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ontology.world_state import WorldState
from world.battle_grid import BattleGrid

if TYPE_CHECKING:
    from agent.agent import Agent


@dataclass
class Observation:
    """A single perceived fact, in natural-language-ready form."""

    category: str  # "agent_position", "agent_action", "agent_status", "event"
    description: str
    subject: str  # who/what is being observed
    details: dict  # structured data for downstream use


class PerceptionEngine:
    """Filters WorldState into per-agent observations based on spatial proximity."""

    def __init__(
        self,
        world_state: WorldState,
        grid: BattleGrid,
        perception_radius: int = 8,
    ) -> None:
        self.world_state = world_state
        self.grid = grid
        self.perception_radius = perception_radius

    def perceive(
        self,
        observer: Agent,
        all_agents: list[Agent],
        recent_actions: dict[str, dict] | None = None,
    ) -> list[Observation]:
        """Generate observations for `observer` based on current world state.

        Args:
            observer: the agent doing the perceiving
            all_agents: all agents in the simulation
            recent_actions: mapping agent_id -> {action_type, description, ...}
                for actions that happened since last perception
        """
        observations: list[Observation] = []
        obs_pos = self.world_state.get_position(observer.agent_id)
        if obs_pos is None:
            return observations

        ox, oy = BattleGrid.parse_tile(obs_pos)

        # Find all agents within perception radius
        for agent in all_agents:
            if agent.agent_id == observer.agent_id:
                continue
            if not agent.is_alive:
                continue

            agent_pos = self.world_state.get_position(agent.agent_id)
            if agent_pos is None:
                continue

            ax, ay = BattleGrid.parse_tile(agent_pos)
            dist = BattleGrid.manhattan(ox, oy, ax, ay)

            if dist > self.perception_radius:
                continue

            # Agent position observation
            observations.append(
                Observation(
                    category="agent_position",
                    description=f"{agent.identity.name} is at tile ({ax}, {ay}), distance {dist}.",
                    subject=agent.agent_id,
                    details={
                        "agent_id": agent.agent_id,
                        "name": agent.identity.name,
                        "tile": agent_pos,
                        "distance": dist,
                        "hp": agent.attributes.hp,
                        "max_hp": agent.attributes.max_hp,
                    },
                )
            )

            # Agent status observations
            statuses = self.world_state.get_statuses(agent.agent_id)
            if statuses:
                observations.append(
                    Observation(
                        category="agent_status",
                        description=f"{agent.identity.name} appears to be: {', '.join(statuses)}.",
                        subject=agent.agent_id,
                        details={"statuses": statuses},
                    )
                )

        # Recent actions within perception radius
        if recent_actions:
            for agent_id, action_info in recent_actions.items():
                if agent_id == observer.agent_id:
                    continue
                agent_pos = self.world_state.get_position(agent_id)
                if agent_pos is None:
                    continue
                ax, ay = BattleGrid.parse_tile(agent_pos)
                dist = BattleGrid.manhattan(ox, oy, ax, ay)
                if dist <= self.perception_radius:
                    observations.append(
                        Observation(
                            category="agent_action",
                            description=action_info.get(
                                "description", f"{agent_id} did something."
                            ),
                            subject=agent_id,
                            details=action_info,
                        )
                    )

        return observations

    def format_perception_text(
        self, observer: Agent, observations: list[Observation]
    ) -> str:
        """Render observations into a natural-language block for LLM prompts."""
        if not observations:
            return "You see nothing noteworthy nearby."

        lines = [f"[Perceptions for {observer.identity.name}]"]
        for obs in observations:
            lines.append(f"- {obs.description}")
        return "\n".join(lines)
