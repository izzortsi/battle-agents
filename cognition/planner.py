"""Planner — hierarchical plan generation for combat agents.

High-level plan: generated at battle start or after major events.
Immediate plan: decomposed from high-level plan each turn.

Plans are stored as MemoryNode(type=PLAN) and participate in retrieval.

Major event triggers for re-planning:
  - Battle start (round 1)
  - Ally dies
  - HP drops below 30%
  - New enemy appears in perception
  - Significant disposition change (alliance formed/broken)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cognition.memory_stream import MemoryStream, MemoryType
from cognition.retrieval import retrieve
from llm.json_utils import extract_json
from llm.prompts.planning import (
    build_immediate_plan_prompts,
    build_plan_prompts,
    format_relationships_for_plan,
)

if TYPE_CHECKING:
    from agent.agent import Agent
    from llm.adapter import LLMAdapter
    from world.environment import Environment

log = logging.getLogger(__name__)


class Planner:
    """Manages high-level and immediate plans for an agent."""

    def __init__(self) -> None:
        # agent_id -> current high-level plan text
        self._plans: dict[str, str] = {}
        # agent_id -> last HP ratio when plan was generated
        self._last_hp_ratio: dict[str, float] = {}
        # agent_id -> set of known enemy IDs when plan was generated
        self._known_enemies: dict[str, set[str]] = {}
        # agent_id -> set of known ally IDs when plan was generated
        self._known_allies: dict[str, set[str]] = {}

    def get_current_plan(self, agent_id: str) -> str:
        """Get the current high-level plan for an agent (empty if none)."""
        return self._plans.get(agent_id, "")

    def should_replan(
        self,
        agent: Agent,
        env: Environment,
        round_number: int,
    ) -> tuple[bool, str]:
        """Check if the agent should generate a new high-level plan.

        Returns (should_replan, trigger_context).
        """
        agent_id = agent.agent_id

        # No plan yet — always plan at battle start
        if agent_id not in self._plans:
            return True, "Battle has just begun. Create your initial strategy."

        # HP dropped below 30%
        hp_ratio = agent.attributes.hp / max(agent.attributes.max_hp, 1)
        last_ratio = self._last_hp_ratio.get(agent_id, 1.0)
        if hp_ratio < 0.3 and last_ratio >= 0.3:
            return True, (
                f"Your HP has dropped critically low ({agent.attributes.hp}/"
                f"{agent.attributes.max_hp}). Reassess your strategy."
            )

        # New enemy appeared
        current_enemies = set()
        for other in env.alive_agents():
            if other.agent_id != agent_id:
                current_enemies.add(other.agent_id)
        known = self._known_enemies.get(agent_id, set())
        new_enemies = current_enemies - known
        if new_enemies and known:  # Don't trigger on first perception
            names = [env.agents[eid].name for eid in new_enemies if eid in env.agents]
            return True, f"New threat detected: {', '.join(names)}. Reassess."

        # Ally died (someone who was in allies set is no longer alive)
        current_allies = set(agent.social.get_allies())
        old_allies = self._known_allies.get(agent_id, set())
        lost_allies = old_allies - current_allies
        dead_allies = [
            aid
            for aid in lost_allies
            if aid in env.agents and not env.agents[aid].is_alive
        ]
        if dead_allies:
            names = [env.agents[aid].name for aid in dead_allies if aid in env.agents]
            return True, f"Ally lost: {', '.join(names)}. Reassess your strategy."

        return False, ""

    _DEFAULT_FALLBACK_PLAN = "Fight cautiously and look for opportunities."

    def generate_plan(
        self,
        agent: Agent,
        env: Environment,
        memory: MemoryStream,
        llm: LLMAdapter,
        round_number: int,
        current_turn: int,
        trigger_context: str = "",
        location_context: str = "",
        plan_directives: str = "",
        closing_instruction: str = "",
        show_combat_stats: bool = True,
        retrieval_query: str = "",
        fallback_plan: str = "",
    ) -> str:
        """Generate a new high-level plan for the agent.

        Stores the plan as a MemoryNode and updates internal tracking.
        Returns the plan text.
        """
        from world.battle_grid import BattleGrid

        pos = env.world_state.get_position(agent.agent_id)
        mx, my = BattleGrid.parse_tile(pos) if pos else (0, 0)

        # Build relationship context
        relationships: dict[str, tuple[float, str]] = {}
        for other in env.alive_agents():
            if other.agent_id == agent.agent_id:
                continue
            rel = agent.social.get_relationship(other.agent_id)
            if rel:
                disp = rel.disposition
                label = (
                    "ally"
                    if disp > 0.5
                    else "friendly"
                    if disp > 0.0
                    else "neutral"
                    if disp > -0.3
                    else "hostile"
                )
                relationships[other.name] = (disp, label)
            else:
                relationships[other.name] = (0.0, "unknown")

        relationships_text = format_relationships_for_plan(relationships)

        # Retrieve memories for planning context
        query = retrieval_query or f"{agent.name} strategy plan combat"
        relevant = retrieve(memory, query, current_turn, top_k=10)

        personality = ", ".join(agent.identity.personality_traits) or "unknown"

        system, user = build_plan_prompts(
            agent_name=agent.name,
            combat_class=agent.identity.combat_class,
            personality=personality,
            backstory=agent.identity.backstory,
            round_number=round_number,
            my_x=mx,
            my_y=my,
            hp=agent.attributes.hp,
            max_hp=agent.attributes.max_hp,
            mana=agent.attributes.mana,
            max_mana=agent.attributes.max_mana,
            atk=agent.attributes.atk,
            mgk=agent.attributes.mgk,
            spd=agent.attributes.spd,
            con=agent.attributes.con,
            hit=agent.attributes.hit,
            damage_type=agent.attributes.damage_type,
            attack_range=agent.attributes.attack_range,
            relationships_text=relationships_text,
            memories=relevant,
            trigger_context=trigger_context,
            location_context=location_context,
            plan_directives=plan_directives,
            closing_instruction=closing_instruction,
            show_combat_stats=show_combat_stats,
        )

        _fallback = fallback_plan or self._DEFAULT_FALLBACK_PLAN
        plan_text = ""
        try:
            raw = llm.complete(
                system=system,
                user=user,
                max_tokens=256,
                temperature=0.7,
                response_format="json",
            )
            parsed = extract_json(raw)
            if isinstance(parsed, dict) and "plan" in parsed:
                plan_text = str(parsed["plan"])
        except Exception as e:
            log.warning(f"  [{agent.name}] Plan generation failed: {e}")
            plan_text = _fallback

        if not plan_text:
            plan_text = _fallback

        # Store as a plan memory
        memory.add(
            turn=current_turn,
            memory_type=MemoryType.PLAN,
            description=f"My plan: {plan_text}",
            poignancy=7,
            depth=0,
            subject=agent.name,
            predicate="plans",
            object_=plan_text[:50],
        )

        # Update tracking state
        self._plans[agent.agent_id] = plan_text
        self._last_hp_ratio[agent.agent_id] = agent.attributes.hp / max(
            agent.attributes.max_hp, 1
        )
        self._known_enemies[agent.agent_id] = {
            other.agent_id
            for other in env.alive_agents()
            if other.agent_id != agent.agent_id
        }
        self._known_allies[agent.agent_id] = set(agent.social.get_allies())

        log.info(f"  [{agent.name}] New plan: {plan_text}")
        return plan_text

    def maybe_replan(
        self,
        agent: Agent,
        env: Environment,
        memory: MemoryStream,
        llm: LLMAdapter,
        round_number: int,
        current_turn: int,
    ) -> str:
        """Check if replanning is needed, and if so, generate a new plan.

        Returns the current plan text (new or existing).
        """
        should, trigger = self.should_replan(agent, env, round_number)
        if should:
            return self.generate_plan(
                agent, env, memory, llm, round_number, current_turn, trigger
            )
        return self.get_current_plan(agent.agent_id)

    # ------------------------------------------------------------------
    # Async variants
    # ------------------------------------------------------------------

    async def async_generate_plan(
        self,
        agent: Agent,
        env: Environment,
        memory: MemoryStream,
        llm: LLMAdapter,
        round_number: int,
        current_turn: int,
        trigger_context: str = "",
        location_context: str = "",
        plan_directives: str = "",
        closing_instruction: str = "",
        show_combat_stats: bool = True,
        retrieval_query: str = "",
        fallback_plan: str = "",
    ) -> str:
        """Async version of generate_plan(). Calls llm.async_complete()."""
        from world.battle_grid import BattleGrid

        pos = env.world_state.get_position(agent.agent_id)
        mx, my = BattleGrid.parse_tile(pos) if pos else (0, 0)

        relationships: dict[str, tuple[float, str]] = {}
        for other in env.alive_agents():
            if other.agent_id == agent.agent_id:
                continue
            rel = agent.social.get_relationship(other.agent_id)
            if rel:
                disp = rel.disposition
                label = (
                    "ally"
                    if disp > 0.5
                    else "friendly"
                    if disp > 0.0
                    else "neutral"
                    if disp > -0.3
                    else "hostile"
                )
                relationships[other.name] = (disp, label)
            else:
                relationships[other.name] = (0.0, "unknown")

        relationships_text = format_relationships_for_plan(relationships)

        query = retrieval_query or f"{agent.name} strategy plan combat"
        relevant = retrieve(memory, query, current_turn, top_k=10)

        personality = ", ".join(agent.identity.personality_traits) or "unknown"

        system, user = build_plan_prompts(
            agent_name=agent.name,
            combat_class=agent.identity.combat_class,
            personality=personality,
            backstory=agent.identity.backstory,
            round_number=round_number,
            my_x=mx,
            my_y=my,
            hp=agent.attributes.hp,
            max_hp=agent.attributes.max_hp,
            mana=agent.attributes.mana,
            max_mana=agent.attributes.max_mana,
            atk=agent.attributes.atk,
            mgk=agent.attributes.mgk,
            spd=agent.attributes.spd,
            con=agent.attributes.con,
            hit=agent.attributes.hit,
            damage_type=agent.attributes.damage_type,
            attack_range=agent.attributes.attack_range,
            relationships_text=relationships_text,
            memories=relevant,
            trigger_context=trigger_context,
            location_context=location_context,
            plan_directives=plan_directives,
            closing_instruction=closing_instruction,
            show_combat_stats=show_combat_stats,
        )

        _fallback = fallback_plan or self._DEFAULT_FALLBACK_PLAN
        plan_text = ""
        try:
            raw = await llm.async_complete(
                system=system,
                user=user,
                max_tokens=256,
                temperature=0.7,
                response_format="json",
            )
            parsed = extract_json(raw)
            if isinstance(parsed, dict) and "plan" in parsed:
                plan_text = str(parsed["plan"])
        except Exception as e:
            log.warning(f"  [{agent.name}] Plan generation failed: {e}")
            plan_text = _fallback

        if not plan_text:
            plan_text = _fallback

        memory.add(
            turn=current_turn,
            memory_type=MemoryType.PLAN,
            description=f"My plan: {plan_text}",
            poignancy=7,
            depth=0,
            subject=agent.name,
            predicate="plans",
            object_=plan_text[:50],
        )

        self._plans[agent.agent_id] = plan_text
        self._last_hp_ratio[agent.agent_id] = agent.attributes.hp / max(
            agent.attributes.max_hp, 1
        )
        self._known_enemies[agent.agent_id] = {
            other.agent_id
            for other in env.alive_agents()
            if other.agent_id != agent.agent_id
        }
        self._known_allies[agent.agent_id] = set(agent.social.get_allies())

        log.info(f"  [{agent.name}] New plan: {plan_text}")
        return plan_text

    async def async_maybe_replan(
        self,
        agent: Agent,
        env: Environment,
        memory: MemoryStream,
        llm: LLMAdapter,
        round_number: int,
        current_turn: int,
    ) -> str:
        """Async version of maybe_replan(). Calls async_generate_plan()."""
        should, trigger = self.should_replan(agent, env, round_number)
        if should:
            return await self.async_generate_plan(
                agent, env, memory, llm, round_number, current_turn, trigger
            )
        return self.get_current_plan(agent.agent_id)
