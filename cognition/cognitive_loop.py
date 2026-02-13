"""Cognitive loop — orchestrates the full per-turn cognitive cycle.

Phase 3: Full generative agent architecture with:
  PERCEIVE → REMEMBER → REFLECT → PLAN → RETRIEVE → DECIDE → (CHAT)

Each agent gets a CognitiveState that persists across turns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from combat.actions import ActionType
from cognition.decision import decide
from cognition.dialogue import run_dialogue_session
from cognition.memory_stream import MemoryStream, MemoryType
from cognition.perceiver import perceive_to_memory
from cognition.planner import Planner
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
    ) -> None:
        self.llm = llm
        self._states: dict[str, CognitiveState] = {}
        self._default_top_k = retrieval_top_k
        self._default_decay = retrieval_decay
        self._chat_max_rounds = chat_max_rounds
        self._reflection_threshold = reflection_threshold
        self._planner = Planner()

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
    ) -> CombatAction:
        """Execute one cognitive turn for the given agent.

        Steps:
        1. PERCEIVE — get observations from environment
        2. REMEMBER — convert observations to MemoryNodes
        3. REFLECT  — if importance threshold met, generate insights
        4. PLAN     — check if replanning needed, generate/update plan
        5. RETRIEVE — score and select top-K relevant memories
        6. DECIDE   — LLM selects an action (with plan context)
        7. (if CHAT) — run dialogue session

        Returns the chosen CombatAction.
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

        # 6. DECIDE — call LLM to select action (with plan context)
        action = decide(
            agent=agent,
            env=env,
            perceptions_text=perceptions_text,
            memories=retrieved,
            llm=self.llm,
            round_number=round_number,
            current_plan=current_plan,
        )

        # 7. Handle CHAT — run dialogue session if the decision is to chat
        if action.action_type == ActionType.CHAT and action.target_agent:
            self._handle_chat(agent, action, env, round_number)

        return action

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
