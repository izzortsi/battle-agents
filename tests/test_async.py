"""Tests for async concurrency layer.

Verifies that async wrappers for reflection, planning, decision, and
the cognitive loop produce the same results as their sync counterparts.
"""

from __future__ import annotations

import asyncio

import pytest

from cognition.decision import async_decide, CombatDecision
from cognition.memory_stream import MemoryStream, MemoryType
from cognition.planner import Planner
from cognition.pre_battle_decision import async_decide_pre_battle, PreBattleDecision
from cognition.reflection import async_reflect
from combat.actions import ActionType

from tests.conftest import MockLLM, make_agent, populate_memory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory_with_importance(threshold: float = 50.0) -> MemoryStream:
    """Create a MemoryStream with enough importance to trigger reflection."""
    ms = MemoryStream()
    # Add enough memories with high poignancy to cross threshold
    for i in range(10):
        ms.add(
            turn=i,
            memory_type=MemoryType.OBSERVATION,
            description=f"Important event {i}: a fierce battle erupted nearby",
            poignancy=8,
            subject="kael",
            predicate="observed",
            object_=f"battle_{i}",
        )
    return ms


# ---------------------------------------------------------------------------
# Async reflection tests
# ---------------------------------------------------------------------------


class TestAsyncReflect:
    @pytest.mark.asyncio
    async def test_below_threshold_returns_empty(self):
        """Async reflect skips when importance is below threshold."""
        ms = MemoryStream()
        populate_memory(ms, 5)  # low importance
        llm = MockLLM()

        result = await async_reflect(
            agent_name="Kael",
            combat_class="warrior",
            memory=ms,
            llm=llm,
            current_turn=10,
            threshold=999.0,
        )
        assert result == []
        assert llm._call_count == 0

    @pytest.mark.asyncio
    async def test_generates_reflections(self):
        """Async reflect generates insights when threshold is met."""
        ms = _make_memory_with_importance()

        llm = MockLLM(
            responses=[
                # Question generation
                '{"questions": ["What threats exist?", "Who are my allies?", "What is my strategy?"]}',
                # Insight for question 1
                '{"insight": "The battlefield is dangerous", "evidence": [1, 2]}',
                # Insight for question 2
                '{"insight": "I have no clear allies yet", "evidence": [3]}',
                # Insight for question 3
                '{"insight": "I should be cautious", "evidence": [4, 5]}',
            ]
        )

        result = await async_reflect(
            agent_name="Kael",
            combat_class="warrior",
            memory=ms,
            llm=llm,
            current_turn=15,
            threshold=50.0,
        )
        assert len(result) > 0
        assert ms.importance_accumulator == 0  # reset after reflection


# ---------------------------------------------------------------------------
# Async planner tests
# ---------------------------------------------------------------------------


class TestAsyncPlanner:
    @pytest.mark.asyncio
    async def test_async_generate_plan(self):
        """Async generate_plan produces a plan and stores it in memory."""
        from world.battle_grid import BattleGrid
        from world.environment import Environment

        grid = BattleGrid(width=10, height=10)
        env = Environment(grid=grid, perception_radius=8)

        agent = make_agent("kael", "Kael", "warrior")
        env.register_agent(agent, 3, 3)

        ms = MemoryStream()
        llm = MockLLM(responses=['{"plan": "Attack the nearest enemy aggressively"}'])

        planner = Planner()
        plan = await planner.async_generate_plan(
            agent=agent,
            env=env,
            memory=ms,
            llm=llm,
            round_number=1,
            current_turn=1,
            trigger_context="Battle has just begun.",
        )

        assert "Attack the nearest enemy" in plan
        assert planner.get_current_plan("kael") == plan
        # Plan should be stored as a memory
        assert len(ms) > 0

    @pytest.mark.asyncio
    async def test_async_maybe_replan_triggers(self):
        """Async maybe_replan triggers when no plan exists."""
        from world.battle_grid import BattleGrid
        from world.environment import Environment

        grid = BattleGrid(width=10, height=10)
        env = Environment(grid=grid, perception_radius=8)

        agent = make_agent("kael", "Kael", "warrior")
        env.register_agent(agent, 3, 3)

        ms = MemoryStream()
        llm = MockLLM(responses=['{"plan": "Defend and wait for opportunity"}'])

        planner = Planner()
        plan = await planner.async_maybe_replan(
            agent=agent,
            env=env,
            memory=ms,
            llm=llm,
            round_number=1,
            current_turn=1,
        )
        assert plan  # should have generated a plan
        assert llm._call_count == 1


# ---------------------------------------------------------------------------
# Async decision tests
# ---------------------------------------------------------------------------


class TestAsyncDecide:
    @pytest.mark.asyncio
    async def test_async_decide_wait_fallback(self):
        """Async decide falls back to WAIT on default mock response."""
        from world.battle_grid import BattleGrid
        from world.environment import Environment

        grid = BattleGrid(width=10, height=10)
        env = Environment(grid=grid, perception_radius=8)

        agent = make_agent("kael", "Kael", "warrior")
        env.register_agent(agent, 3, 3)

        llm = MockLLM()  # default: '{"action": "wait"}'

        decision = await async_decide(
            agent=agent,
            env=env,
            perceptions_text="You see nothing noteworthy nearby.",
            memories=[],
            llm=llm,
            round_number=1,
        )
        assert isinstance(decision, CombatDecision)
        assert decision.primary_action.action_type == ActionType.WAIT

    @pytest.mark.asyncio
    async def test_async_decide_attack(self):
        """Async decide can produce an attack action."""
        from world.battle_grid import BattleGrid
        from world.environment import Environment

        grid = BattleGrid(width=10, height=10)
        env = Environment(grid=grid, perception_radius=8)

        attacker = make_agent("kael", "Kael", "warrior")
        target = make_agent("vorn", "Vorn", "rogue")
        env.register_agent(attacker, 3, 3)
        env.register_agent(target, 3, 4)  # adjacent

        llm = MockLLM(
            responses=['{"action": "attack", "target_agent": "vorn", "reasoning": "Strike!"}']
        )

        decision = await async_decide(
            agent=attacker,
            env=env,
            perceptions_text="Vorn is nearby.",
            memories=[],
            llm=llm,
            round_number=1,
        )
        assert decision.primary_action.action_type == ActionType.ATTACK
        assert decision.primary_action.target_agent == "vorn"


# ---------------------------------------------------------------------------
# Async pre-battle decision tests
# ---------------------------------------------------------------------------


class TestAsyncPreBattleDecide:
    @pytest.mark.asyncio
    async def test_async_pre_battle_decide_wait(self):
        """Async pre-battle decide returns WAIT on default response."""
        from world.battle_grid import BattleGrid
        from world.environment import Environment

        grid = BattleGrid(width=10, height=10)
        env = Environment(grid=grid, perception_radius=12)

        agent = make_agent("kael", "Kael", "warrior")
        env.register_agent(agent, 3, 3)

        llm = MockLLM()

        decision = await async_decide_pre_battle(
            agent=agent,
            env=env,
            perceptions_text="The arena is quiet.",
            memories=[],
            llm=llm,
            tick_number=1,
            total_ticks=4,
        )
        assert isinstance(decision, PreBattleDecision)
        assert decision.primary_action.action_type == ActionType.WAIT


# ---------------------------------------------------------------------------
# Async cognitive loop tests
# ---------------------------------------------------------------------------


class TestAsyncCognitiveLoop:
    @pytest.mark.asyncio
    async def test_async_run_turn(self):
        """Async run_turn produces a valid CombatDecision."""
        from cognition.cognitive_loop import CognitiveLoop
        from world.battle_grid import BattleGrid
        from world.environment import Environment

        grid = BattleGrid(width=10, height=10)
        env = Environment(grid=grid, perception_radius=8)

        agent = make_agent("kael", "Kael", "warrior")
        env.register_agent(agent, 3, 3)
        env.start_combat()

        llm = MockLLM(
            responses=[
                # Plan generation
                '{"plan": "Fight aggressively"}',
                # Decision
                '{"action": "wait", "reasoning": "Assessing the situation"}',
            ]
        )

        loop = CognitiveLoop(llm=llm)
        loop.register(agent)

        decision = await loop.async_run_turn(agent, env, round_number=1)
        assert isinstance(decision, CombatDecision)

    @pytest.mark.asyncio
    async def test_async_pre_battle_tick_parallel(self):
        """Async pre-battle tick processes multiple agents."""
        from cognition.cognitive_loop import CognitiveLoop
        from world.battle_grid import BattleGrid
        from world.environment import Environment

        grid = BattleGrid(width=10, height=10)
        env = Environment(grid=grid, perception_radius=12)

        agents = [
            make_agent("kael", "Kael", "warrior"),
            make_agent("lyra", "Lyra", "mage"),
            make_agent("vorn", "Vorn", "rogue"),
        ]

        env.register_agent(agents[0], 2, 2)
        env.register_agent(agents[1], 5, 5)
        env.register_agent(agents[2], 8, 8)

        # Need enough responses: plan + decision for each agent
        llm = MockLLM(
            responses=[
                '{"plan": "Socialize and scout"}',
                '{"action": "wait", "reasoning": "Observing"}',
                '{"plan": "Find allies"}',
                '{"action": "wait", "reasoning": "Looking around"}',
                '{"plan": "Stay hidden"}',
                '{"action": "wait", "reasoning": "Being cautious"}',
            ]
        )

        loop = CognitiveLoop(llm=llm)
        for a in agents:
            loop.register(a)

        decisions = await loop.async_run_pre_battle_tick(
            agents=agents,
            env=env,
            tick_number=1,
            total_ticks=4,
        )

        assert len(decisions) == 3
        for agent, decision in decisions:
            assert isinstance(decision, PreBattleDecision)

    @pytest.mark.asyncio
    async def test_async_pre_battle_graceful_error(self):
        """Async pre-battle tick handles errors gracefully."""
        from cognition.cognitive_loop import CognitiveLoop
        from world.battle_grid import BattleGrid
        from world.environment import Environment

        grid = BattleGrid(width=10, height=10)
        env = Environment(grid=grid, perception_radius=12)

        agent = make_agent("kael", "Kael", "warrior")
        env.register_agent(agent, 3, 3)

        # LLM that raises on every call
        class FailingLLM(MockLLM):
            def complete(self, *args, **kwargs):
                raise RuntimeError("LLM is down!")

            async def async_complete(self, *args, **kwargs):
                raise RuntimeError("LLM is down!")

        llm = FailingLLM()
        loop = CognitiveLoop(llm=llm)
        loop.register(agent)

        decisions = await loop.async_run_pre_battle_tick(
            agents=[agent],
            env=env,
            tick_number=1,
            total_ticks=4,
        )

        # Should still get a decision (WAIT fallback from error handling)
        assert len(decisions) == 1
        _, decision = decisions[0]
        assert decision.primary_action.action_type == ActionType.WAIT
