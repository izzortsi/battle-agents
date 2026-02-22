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
from world.alliance_resolver import AllianceStatus, resolve_alliance
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
        victory_mode: str = "last_standing",
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
        self.victory_mode = victory_mode
        self.death_log: list[
            dict
        ] = []  # [{agent_id, name, combat_class, killer, method, round}]
        self.damage_dealt: dict[str, int] = {}  # agent_id -> total damage dealt
        self.round_number: int = 0  # current round (set by runner)

        # Chat distance limits (set per-phase by the runner)
        self.chat_speak_radius: int = 99  # default: no limit
        self.chat_listen_radius: int = 99

    # -- Setup -----------------------------------------------------------------

    def register_agent(self, agent: Agent, x: int, y: int) -> None:
        # Seed initial dispositions based on alignment compatibility
        for other in self.agents.values():
            if other.agent_id == agent.agent_id:
                continue
            bias = agent.alignment.compatibility(other.alignment)
            if bias != 0.0:
                agent.social.ensure_relationship(
                    other.agent_id, other.identity.name, initial_bias=bias
                )
                other.social.ensure_relationship(
                    agent.agent_id, agent.identity.name, initial_bias=bias
                )

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

    # -- Player action support -------------------------------------------------

    def get_legal_actions(self, agent_id: str) -> dict:
        """Compute all legal actions for a player-controlled agent.

        Returns a dict suitable for serialization and broadcast to the
        frontend as part of the ``awaiting_player`` WebSocket message.
        """
        agent = self.agents.get(agent_id)
        if not agent or not agent.is_alive:
            return {"agent_id": agent_id, "actions": {}}

        pos = self.world_state.get_position(agent_id)
        if pos is None:
            return {"agent_id": agent_id, "actions": {}}

        ax, ay = BattleGrid.parse_tile(pos)
        attrs = agent.attributes

        # Occupied tile keys (can't move onto another agent)
        occupied: set[str] = set()
        for other in self.alive_agents():
            if other.agent_id == agent_id:
                continue
            opos = self.world_state.get_position(other.agent_id)
            if opos:
                occupied.add(opos)

        # -- Movement tiles --
        reachable = self.grid.reachable_tiles(
            ax,
            ay,
            attrs.move_range,
            attrs.jump,
            occupied=occupied,
        )
        valid_moves = [
            BattleGrid.tile_key(mx, my)
            for (mx, my) in reachable
            if BattleGrid.tile_key(mx, my) != pos
        ]
        valid_moves.sort(key=lambda t: BattleGrid.tile_distance(pos, t))

        # -- Attack targets --
        attack_targets = []
        for other in self.alive_agents():
            if other.agent_id == agent_id:
                continue
            opos = self.world_state.get_position(other.agent_id)
            if opos is None:
                continue
            ox, oy = BattleGrid.parse_tile(opos)
            dist = BattleGrid.manhattan(ax, ay, ox, oy)
            if dist <= attrs.attack_range:
                attack_targets.append({
                    "agent_id": other.agent_id,
                    "name": other.name,
                    "distance": dist,
                    "hp": other.attributes.hp,
                    "max_hp": other.attributes.max_hp,
                })

        # -- Abilities --
        abilities_info = []
        for ability in getattr(attrs, "abilities", []):
            cd = ability.get("current_cd", 0)
            mana_cost = ability.get("mana_cost", 0)
            can_use = cd <= 0 and attrs.mana >= mana_cost
            ab_range = ability.get("range", 1)

            # Self-targeting check: any effect with target="self"
            effects = ability.get("effects", [])
            is_self = any(
                e.get("target") == "self" for e in effects if isinstance(e, dict)
            )

            targets = []
            if is_self:
                targets.append({
                    "agent_id": agent_id,
                    "name": agent.name,
                    "distance": 0,
                })

            for other in self.alive_agents():
                if other.agent_id == agent_id:
                    continue
                opos = self.world_state.get_position(other.agent_id)
                if opos is None:
                    continue
                ox, oy = BattleGrid.parse_tile(opos)
                dist = BattleGrid.manhattan(ax, ay, ox, oy)
                if dist <= ab_range:
                    targets.append({
                        "agent_id": other.agent_id,
                        "name": other.name,
                        "distance": dist,
                    })

            abilities_info.append({
                "name": ability.get("name", "Unknown"),
                "mana_cost": mana_cost,
                "damage": ability.get("damage", 0),
                "range": ab_range,
                "aoe_pattern": ability.get("aoe_pattern", "single"),
                "cooldown_remaining": cd,
                "can_use": can_use,
                "description": ability.get("description", ""),
                "is_self_targeting": is_self,
                "targets": targets,
            })

        # -- Chat targets --
        chat_targets = []
        for other in self.alive_agents():
            if other.agent_id == agent_id:
                continue
            opos = self.world_state.get_position(other.agent_id)
            if opos is None:
                continue
            ox, oy = BattleGrid.parse_tile(opos)
            dist = BattleGrid.manhattan(ax, ay, ox, oy)
            if dist <= self.chat_speak_radius:
                chat_targets.append({
                    "agent_id": other.agent_id,
                    "name": other.name,
                    "distance": dist,
                })

        return {
            "agent_id": agent_id,
            "position": {"x": ax, "y": ay},
            "move_range": attrs.move_range,
            "jump": attrs.jump,
            "valid_moves": valid_moves,
            "attack_range": attrs.attack_range,
            "attack_targets": attack_targets,
            "abilities": abilities_info,
            "chat_targets": chat_targets,
            "can_defend": True,
            "can_wait": True,
        }

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
            "target_agent": action.target_agent,
            **result.details,
        }

        # Track damage dealt for campaign XP
        if result.success:
            dmg = result.details.get("damage", 0)
            if dmg > 0:
                self.damage_dealt[action.agent_id] = (
                    self.damage_dealt.get(action.agent_id, 0) + dmg
                )

        # Post-resolution social model updates
        if result.success:
            self._update_social_models(action, result)

        return result

    def _update_social_models(self, action: CombatAction, result: ActionResult) -> None:
        """Update social models and alignment drift based on resolved combat events."""
        from combat.actions import ActionType

        turn = self.turn_manager.global_turn

        # -- Alignment drift for defend --
        if action.action_type == ActionType.DEFEND:
            agent = self.agents.get(action.agent_id)
            if agent:
                agent.alignment.apply_drift("defend")

        # -- Alignment drift: spare low-HP enemy (WAIT/DEFEND with low-HP foe in range) --
        if action.action_type in (ActionType.WAIT, ActionType.DEFEND):
            agent = self.agents.get(action.agent_id)
            if agent:
                pos = self.world_state.get_position(agent.agent_id)
                if pos:
                    ax, ay = BattleGrid.parse_tile(pos)
                    atk_range = agent.attributes.attack_range
                    for other in self.alive_agents():
                        if other.agent_id == agent.agent_id:
                            continue
                        opos = self.world_state.get_position(other.agent_id)
                        if opos is None:
                            continue
                        ox, oy = BattleGrid.parse_tile(opos)
                        dist = BattleGrid.manhattan(ax, ay, ox, oy)
                        alliance = self.get_alliance_status(
                            agent.agent_id, other.agent_id
                        )
                        if (
                            dist <= atk_range
                            and not alliance.is_positive
                            and other.attributes.hp < other.attributes.max_hp * 0.2
                        ):
                            agent.alignment.apply_drift("spare_low_hp")
                            break  # one drift per turn is enough

        if (
            action.action_type in (ActionType.ATTACK, ActionType.ABILITY)
            and action.target_agent
        ):
            attacker = self.agents.get(action.agent_id)
            target = self.agents.get(action.target_agent)
            if not attacker or not target:
                return

            damage = result.details.get("damage", 0)
            killed = result.details.get("killed", False)
            # For ABILITY, check kills list instead of single killed flag
            if action.action_type == ActionType.ABILITY:
                kills = result.details.get("kills", [])
                killed = len(kills) > 0

            # -- Alignment drift for combat events --
            alliance = self.get_alliance_status(attacker.agent_id, target.agent_id)

            # Attack ally → evil drift (only for strong ALLIED bonds)
            if alliance == AllianceStatus.ALLIED:
                attacker.alignment.apply_drift("attack_ally")
                # If alliance was declared, this is betrayal
                rel = attacker.social.get_relationship(target.agent_id)
                if rel and rel.alliance_declared:
                    attacker.alignment.apply_drift("betray_alliance")

            # Heal/buff ally (ability with heal effects, no damage)
            if action.action_type == ActionType.ABILITY and damage == 0:
                effects = result.details.get("effects_applied", [])
                if effects and alliance.is_positive:
                    attacker.alignment.apply_drift("heal_ally")

            # Kill blow → slight evil drift
            if killed:
                attacker.alignment.apply_drift("kill_blow")

            # Honor alliance — attacking the same target an ally recently attacked
            if not alliance.is_positive:
                for ally_id, recent in self.recent_actions.items():
                    if ally_id == attacker.agent_id:
                        continue
                    ally_alliance = self.get_alliance_status(attacker.agent_id, ally_id)
                    if (
                        ally_alliance.is_positive
                        and recent.get("action_type") in ("attack", "ability")
                        and recent.get("target_agent") == target.agent_id
                    ):
                        attacker.alignment.apply_drift("honor_alliance")
                        break

            # AoE friendly fire drift (check collateral in kills/hits)
            aoe_hits = result.details.get("aoe_hits", [])
            for hit_id in aoe_hits:
                if hit_id == target.agent_id:
                    continue  # primary target, already handled
                hit_alliance = self.get_alliance_status(attacker.agent_id, hit_id)
                if hit_alliance.is_positive:
                    attacker.alignment.apply_drift("aoe_hit_ally")

            # Target's social model: attacked by attacker
            target.social.on_attacked_by(
                attacker_id=attacker.agent_id,
                turn=turn,
                damage=damage,
                agent_name=attacker.name,
            )

            # Tension spike for player-controlled targets taking damage
            if target.is_player_controlled and damage > 0 and target.attributes.max_hp > 0:
                spike = int((damage / target.attributes.max_hp) * 50)
                if spike > 0:
                    target.tension = min(100, target.tension + spike)
                    log.info(
                        f"  {target.name}: tension +{spike} (took {damage} damage) "
                        f"→ {target.tension}"
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
                        # Tension spike for player-controlled observers
                        if observer.is_player_controlled:
                            observer.tension = min(100, observer.tension + 20)
                            log.info(
                                f"  {observer.name}: tension +20 (ally {target.name} killed) "
                                f"→ {observer.tension}"
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
        if len(alive) <= 1:
            return True
        # Alliance victory: all survivors are mutually ALLIED
        if self.victory_mode == "alliance_victory" and self.all_mutually_allied():
            return True
        return False

    def get_winner(self) -> Agent | None:
        """Return the sole winner, or None for a draw.

        For alliance_victory mode, returns None when multiple allies win
        together — use get_winners() instead.
        """
        alive = self.alive_agents()
        if len(alive) == 1:
            return alive[0]
        return None

    def get_winners(self) -> list[Agent]:
        """Return all winning agents.

        For last_standing: list of 0 or 1 agent.
        For alliance_victory: all surviving allies if mutually ALLIED, else empty.
        """
        alive = self.alive_agents()
        if len(alive) == 1:
            return alive
        if self.victory_mode == "alliance_victory" and self.all_mutually_allied():
            return alive
        return []

    # -- Alliance queries ------------------------------------------------------

    def get_alliance_status(
        self,
        agent_id: str,
        other_id: str,
    ) -> AllianceStatus:
        """Return the mutual alliance status between two agents."""
        agent_a = self.agents.get(agent_id)
        agent_b = self.agents.get(other_id)
        if agent_a is None or agent_b is None:
            return AllianceStatus.NEUTRAL
        return resolve_alliance(
            agent_a.social,
            agent_b.social,
            agent_id,
            other_id,
        )

    def get_all_alliance_statuses(
        self,
        agent_id: str,
    ) -> dict[str, AllianceStatus]:
        """Return alliance statuses for *agent_id* toward every other alive agent."""
        statuses: dict[str, AllianceStatus] = {}
        for other in self.alive_agents():
            if other.agent_id == agent_id:
                continue
            statuses[other.agent_id] = self.get_alliance_status(
                agent_id, other.agent_id
            )
        return statuses

    def all_mutually_allied(self) -> bool:
        """Return True if every pair of alive agents is mutually ALLIED."""
        alive = self.alive_agents()
        if len(alive) <= 1:
            return False  # single survivor is not an "alliance" victory
        for i, a in enumerate(alive):
            for b in alive[i + 1 :]:
                if (
                    self.get_alliance_status(a.agent_id, b.agent_id)
                    != AllianceStatus.ALLIED
                ):
                    return False
        return True

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

    def handle_agent_death(
        self,
        agent_id: str,
        *,
        killer: str = "unknown",
        method: str = "unknown",
        round_num: int = 0,
    ) -> None:
        self.turn_manager.remove_agent(agent_id)
        agent = self.agents.get(agent_id)
        self.death_log.append(
            {
                "agent_id": agent_id,
                "name": agent.name if agent else agent_id,
                "combat_class": (agent.identity.combat_class if agent else "unknown"),
                "killer": killer,
                "method": method,
                "round": round_num,
            }
        )
        log.info(f"{agent_id} has been eliminated.")
