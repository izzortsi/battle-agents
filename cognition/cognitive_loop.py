"""Cognitive loop — orchestrates the full per-turn cognitive cycle.

Phase 4: Full generative agent architecture with pre-battle social phase
  and combat phase.

  Pre-battle: PERCEIVE → REMEMBER → REFLECT → PLAN → RETRIEVE → DECIDE (social)
  Combat:     PERCEIVE → REMEMBER → REFLECT → PLAN → RETRIEVE → DECIDE → (CHAT)

Each agent gets a CognitiveState that persists across both phases.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from cognition.decision import CombatDecision, decide
from cognition.dialogue import run_dialogue_session
from cognition.memory_stream import MemoryStream, MemoryType
from cognition.perceiver import perceive_to_memory
from cognition.planner import Planner
from cognition.pre_battle_decision import PreBattleDecision, decide_pre_battle
from cognition.reflection import reflect
from cognition.retrieval import retrieve

if TYPE_CHECKING:
    from agent.agent import Agent
    from combat.actions import CombatAction
    from llm.adapter import LLMAdapter
    from world.environment import Environment

log = logging.getLogger(__name__)


@dataclass
class CognitiveState:
    """Per-agent persistent cognitive state across turns.

    Each agent gets one of these at battle start; it lives for the
    duration of the battle (and optionally serialises for campaign mode).
    """

    agent_id: str
    memory: MemoryStream = field(default_factory=MemoryStream)

    # Retrieval config (can be overridden per-agent if desired)
    retrieval_top_k: int = 7
    retrieval_decay: float = 0.85


class CognitiveLoop:
    """Stateful cognitive loop for all agents in a battle.

    Usage:
        loop = CognitiveLoop(llm_adapter)
        loop.register(agent)  # for each agent
        ...
        action = loop.run_turn(agent, env, round_number)
    """

    def __init__(
        self,
        llm: LLMAdapter,
        retrieval_top_k: int = 7,
        retrieval_decay: float = 0.85,
        chat_max_rounds: int = 2,
        reflection_threshold: float = 50.0,
        pre_battle_chat_max_rounds: int = 4,
        chat_cooldown: int = 3,
    ) -> None:
        self.llm = llm
        self._states: dict[str, CognitiveState] = {}
        self._default_top_k = retrieval_top_k
        self._default_decay = retrieval_decay
        self._chat_max_rounds = chat_max_rounds
        self._pre_battle_chat_max_rounds = pre_battle_chat_max_rounds
        self._reflection_threshold = reflection_threshold
        self._planner = Planner()
        # Chat cooldown: agent_id -> last round they chatted in combat
        self._chat_cooldown = chat_cooldown
        self._last_chat_round: dict[str, int] = {}

    def register(self, agent: Agent) -> CognitiveState:
        """Register an agent and create its cognitive state."""
        state = CognitiveState(
            agent_id=agent.agent_id,
            retrieval_top_k=self._default_top_k,
            retrieval_decay=self._default_decay,
        )
        self._states[agent.agent_id] = state
        return state

    def get_state(self, agent_id: str) -> CognitiveState | None:
        return self._states.get(agent_id)

    def run_turn(
        self,
        agent: Agent,
        env: Environment,
        round_number: int,
        urgency_text: str = "",
    ) -> CombatDecision:
        """Execute one cognitive turn for the given agent.

        Steps:
        1. PERCEIVE — get observations from environment
        2. REMEMBER — convert observations to MemoryNodes
        3. REFLECT  — if importance threshold met, generate insights
        4. PLAN     — check if replanning needed, generate/update plan
        5. RETRIEVE — score and select top-K relevant memories
        6. DECIDE   — LLM selects an action (with plan context)

        Returns the CombatDecision (primary action + optional chat).
        Chat handling is deferred to the runner.
        """
        state = self._states.get(agent.agent_id)
        if state is None:
            state = self.register(agent)

        current_turn = env.turn_manager.global_turn

        # 1. PERCEIVE
        observations = env.get_perceptions(agent)
        perceptions_text = env.perception_engine.format_perception_text(
            agent, observations
        )

        # 2. REMEMBER — store observations as memory nodes
        new_ids = perceive_to_memory(observations, state.memory, current_turn)
        if new_ids:
            log.debug(
                f"{agent.name}: stored {len(new_ids)} new observations "
                f"(total memories: {len(state.memory)})"
            )

        # 3. REFLECT — if importance accumulator >= threshold
        reflect(
            agent_name=agent.name,
            combat_class=agent.identity.combat_class,
            memory=state.memory,
            llm=self.llm,
            current_turn=current_turn,
            threshold=self._reflection_threshold,
        )

        # 4. PLAN — check if replanning needed
        current_plan = self._planner.maybe_replan(
            agent=agent,
            env=env,
            memory=state.memory,
            llm=self.llm,
            round_number=round_number,
            current_turn=current_turn,
        )

        # 5. RETRIEVE — build a situation query and get relevant memories
        query = self._build_retrieval_query(agent, perceptions_text)
        retrieved = retrieve(
            memory=state.memory,
            query=query,
            current_turn=current_turn,
            top_k=state.retrieval_top_k,
            gamma=state.retrieval_decay,
        )

        # Check chat cooldown
        chat_allowed = self.can_chat_combat(agent.agent_id, round_number)

        # 6. DECIDE — call LLM to select action (with plan context)
        decision = decide(
            agent=agent,
            env=env,
            perceptions_text=perceptions_text,
            memories=retrieved,
            llm=self.llm,
            round_number=round_number,
            current_plan=current_plan,
            chat_allowed=chat_allowed,
            urgency_text=urgency_text,
        )

        return decision

    def _handle_chat(
        self,
        initiator: Agent,
        action: CombatAction,
        env: Environment,
        round_number: int,
    ) -> None:
        """Run a dialogue session when an agent chooses CHAT."""
        target_id = action.target_agent
        if not target_id or target_id not in env.agents:
            return

        responder = env.agents[target_id]
        if not responder.is_alive:
            return

        init_state = self._states.get(initiator.agent_id)
        resp_state = self._states.get(responder.agent_id)
        if not init_state or not resp_state:
            return

        log.info(f"  === Dialogue: {initiator.name} -> {responder.name} ===")

        session = run_dialogue_session(
            initiator=initiator,
            responder=responder,
            initial_message=action.message or "I want to talk.",
            env=env,
            llm=self.llm,
            initiator_memory=init_state.memory,
            responder_memory=resp_state.memory,
            round_number=round_number,
            max_rounds=self._chat_max_rounds,
        )

        log.info(
            f"  === Dialogue ended ({session.status}, "
            f"{len(session.exchanges)} exchanges) ==="
        )

        # Emit overheard observations for nearby agents
        self._emit_overheard(initiator, responder, env)

    def _emit_overheard(
        self,
        initiator: Agent,
        responder: Agent,
        env: Environment,
    ) -> None:
        """Nearby agents get a vague observation that a conversation happened."""
        from world.battle_grid import BattleGrid

        init_pos = env.world_state.get_position(initiator.agent_id)
        if not init_pos:
            return

        current_turn = env.turn_manager.global_turn

        for other in env.alive_agents():
            if other.agent_id in (initiator.agent_id, responder.agent_id):
                continue
            other_pos = env.world_state.get_position(other.agent_id)
            if not other_pos:
                continue

            dist = BattleGrid.tile_distance(init_pos, other_pos)
            if dist <= env.perception_engine.perception_radius:
                state = self._states.get(other.agent_id)
                if state:
                    overheard_desc = (
                        f"{initiator.name} and {responder.name} were seen "
                        f"talking intensely nearby."
                    )
                    state.memory.add(
                        turn=current_turn,
                        memory_type=MemoryType.OBSERVATION,
                        description=overheard_desc,
                        poignancy=4,
                        depth=0,
                        subject=initiator.name,
                        predicate="talked_with",
                        object_=responder.name,
                    )
                    log.debug(f"  {other.name} overheard the dialogue")

    # ==================================================================
    # Chat cooldown
    # ==================================================================

    def can_chat_combat(self, agent_id: str, round_number: int) -> bool:
        """Check if an agent is allowed to chat this combat round."""
        last = self._last_chat_round.get(agent_id, -999)
        return (round_number - last) >= self._chat_cooldown

    def record_chat(self, agent_id: str, round_number: int) -> None:
        """Record that an agent chatted this combat round."""
        self._last_chat_round[agent_id] = round_number

    # ==================================================================
    # Pre-battle social phase
    # ==================================================================

    def run_pre_battle_tick(
        self,
        agents: list[Agent],
        env: Environment,
        tick_number: int,
        total_ticks: int,
    ) -> list[tuple[Agent, PreBattleDecision]]:
        """Execute one simultaneous pre-battle tick for ALL agents.

        All agents perceive, remember, reflect, plan, retrieve, and decide
        in parallel (conceptually — sequentially in code, but all decisions
        are collected before any are resolved).

        Returns a list of (agent, PreBattleDecision) pairs.
        """
        decisions: list[tuple[Agent, PreBattleDecision]] = []

        for agent in agents:
            if not agent.is_alive:
                continue

            state = self._states.get(agent.agent_id)
            if state is None:
                state = self.register(agent)

            # Use a synthetic turn counter for pre-battle ticks
            # (offset so pre-battle ticks don't collide with combat turns)
            current_turn = tick_number

            # 1. PERCEIVE
            observations = env.get_perceptions(agent)
            perceptions_text = env.perception_engine.format_perception_text(
                agent, observations
            )

            # 2. REMEMBER — store observations as memory nodes
            new_ids = perceive_to_memory(observations, state.memory, current_turn)
            if new_ids:
                log.debug(
                    f"{agent.name}: stored {len(new_ids)} new observations "
                    f"(total memories: {len(state.memory)})"
                )

            # 3. REFLECT — if importance accumulator >= threshold
            reflect(
                agent_name=agent.name,
                combat_class=agent.identity.combat_class,
                memory=state.memory,
                llm=self.llm,
                current_turn=current_turn,
                threshold=self._reflection_threshold,
            )

            # 4. PLAN — generate a social plan at the start of pre-battle
            current_plan = self._maybe_social_plan(
                agent, env, state.memory, tick_number, current_turn
            )

            # 5. RETRIEVE — get relevant memories
            query = self._build_social_retrieval_query(agent, perceptions_text)
            retrieved = retrieve(
                memory=state.memory,
                query=query,
                current_turn=current_turn,
                top_k=state.retrieval_top_k,
                gamma=state.retrieval_decay,
            )

            # 6. DECIDE — social action only (chat/move/wait)
            action = decide_pre_battle(
                agent=agent,
                env=env,
                perceptions_text=perceptions_text,
                memories=retrieved,
                llm=self.llm,
                tick_number=tick_number,
                total_ticks=total_ticks,
                current_plan=current_plan,
            )

            decisions.append((agent, action))

        return decisions

    def handle_pre_battle_chat(
        self,
        initiator: Agent,
        action: CombatAction,
        env: Environment,
        tick_number: int,
    ) -> None:
        """Run a dialogue session for a pre-battle CHAT action.

        Uses the pre-battle chat_max_rounds (longer than combat).
        """
        target_id = action.target_agent
        if not target_id or target_id not in env.agents:
            return

        responder = env.agents[target_id]
        if not responder.is_alive:
            return

        init_state = self._states.get(initiator.agent_id)
        resp_state = self._states.get(responder.agent_id)
        if not init_state or not resp_state:
            return

        log.info(f"  === Dialogue: {initiator.name} -> {responder.name} ===")

        session = run_dialogue_session(
            initiator=initiator,
            responder=responder,
            initial_message=action.message or "I want to talk.",
            env=env,
            llm=self.llm,
            initiator_memory=init_state.memory,
            responder_memory=resp_state.memory,
            round_number=tick_number,
            max_rounds=self._pre_battle_chat_max_rounds,
        )

        log.info(
            f"  === Dialogue ended ({session.status}, "
            f"{len(session.exchanges)} exchanges) ==="
        )

        # Emit overheard observations for nearby agents
        self._emit_overheard(initiator, responder, env)

    def _maybe_social_plan(
        self,
        agent: Agent,
        env: Environment,
        memory: MemoryStream,
        tick_number: int,
        current_turn: int,
    ) -> str:
        """Generate a social plan at the start of pre-battle, or return existing.

        Only triggers on tick 1 (first tick of pre-battle). After that,
        the existing plan persists.
        """
        existing = self._planner.get_current_plan(agent.agent_id)
        if existing:
            return existing

        # Generate a social plan at tick 1
        if tick_number <= 1:
            return self._planner.generate_plan(
                agent=agent,
                env=env,
                memory=memory,
                llm=self.llm,
                round_number=tick_number,
                current_turn=current_turn,
                trigger_context=(
                    "A social gathering is about to begin before the battle. "
                    "Plan who you want to talk to, what alliances to form, "
                    "and what information to gather."
                ),
            )
        return ""

    def _build_social_retrieval_query(self, agent: Agent, perceptions_text: str) -> str:
        """Build a retrieval query for the pre-battle social phase."""
        parts = [
            f"{agent.identity.name} is socialising before battle.",
            f"Personality: {', '.join(agent.identity.personality_traits)}.",
        ]
        if (
            perceptions_text
            and perceptions_text != "You see nothing noteworthy nearby."
        ):
            parts.append(perceptions_text)
        return " ".join(parts)

    # ==================================================================
    # Combat phase
    # ==================================================================

    def _build_retrieval_query(self, agent: Agent, perceptions_text: str) -> str:
        """Build a natural-language query for memory retrieval.

        Combines the agent's current situation with perceptions to find
        the most relevant memories.
        """
        parts = [
            f"{agent.identity.name} is in combat.",
            f"HP: {agent.attributes.hp}/{agent.attributes.max_hp}.",
        ]

        # Add a summary of what they just perceived
        if (
            perceptions_text
            and perceptions_text != "You see nothing noteworthy nearby."
        ):
            parts.append(perceptions_text)

        return " ".join(parts)
