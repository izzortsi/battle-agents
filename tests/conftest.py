"""Shared fixtures for battle-agents tests."""

from __future__ import annotations

import pytest

from agent.attributes import Attributes
from agent.identity import Identity
from agent.agent import Agent
from ontology.domain import AgentEntity, EntityType
from ontology.relations import RelationSchema, RelationStore
from ontology.world_state import WorldState
from ontology.knowledge import AgentKnowledge
from cognition.memory_stream import MemoryStream, MemoryType
from world.battle_grid import BattleGrid


# ---------------------------------------------------------------------------
# Ontology fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def relation_store() -> RelationStore:
    """A RelationStore pre-loaded with the standard game schemas."""
    store = RelationStore()
    store.register(RelationSchema("occupies", 2, ("agent", "tile")))
    store.register(RelationSchema("has_status", 2, ("agent", "status")))
    store.register(RelationSchema("holds", 2, ("agent", "object")))
    store.register(RelationSchema("occurred", 2, ("event", "turn")))
    store.register(RelationSchema("has_disposition", 3, ("agent_a", "agent_b", "disp")))
    return store


@pytest.fixture
def world_state(relation_store: RelationStore) -> WorldState:
    return WorldState(relation_store)


# ---------------------------------------------------------------------------
# Grid fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def grid_5x5() -> BattleGrid:
    return BattleGrid(width=5, height=5)


@pytest.fixture
def grid_10x10() -> BattleGrid:
    return BattleGrid(width=10, height=10)


# ---------------------------------------------------------------------------
# Agent fixtures
# ---------------------------------------------------------------------------


def make_agent(
    agent_id: str = "kael",
    name: str = "Kael",
    combat_class: str = "warrior",
    hp: int = 100,
    max_hp: int = 100,
    mana: int = 50,
    max_mana: int = 50,
    attack: int = 15,
    defense: int = 5,
    speed: int = 10,
    attack_range: int = 1,
    move_range: int = 3,
) -> Agent:
    """Helper to create an agent with specific stats."""
    return Agent(
        agent_id=agent_id,
        identity=Identity(name=name, combat_class=combat_class),
        attributes=Attributes(
            max_hp=max_hp,
            hp=hp,
            max_mana=max_mana,
            mana=mana,
            attack=attack,
            defense=defense,
            speed=speed,
            attack_range=attack_range,
            move_range=move_range,
        ),
    )


@pytest.fixture
def kael() -> Agent:
    return make_agent("kael", "Kael", "warrior", speed=12)


@pytest.fixture
def lyra() -> Agent:
    return make_agent("lyra", "Lyra", "mage", speed=8, attack_range=3, mana=80, max_mana=80)


@pytest.fixture
def vorn() -> Agent:
    return make_agent("vorn", "Vorn", "rogue", speed=14)


@pytest.fixture
def mira() -> Agent:
    return make_agent("mira", "Mira", "healer", speed=6)


# ---------------------------------------------------------------------------
# Memory fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def memory_stream() -> MemoryStream:
    return MemoryStream()


def populate_memory(ms: MemoryStream, n: int = 10) -> list[int]:
    """Add n sample memories and return their IDs."""
    ids = []
    for i in range(n):
        node = ms.add(
            turn=i,
            memory_type=MemoryType.OBSERVATION,
            description=f"Test observation {i}",
            poignancy=(i % 10) + 1,
            subject="kael",
            predicate="observed",
            object_=f"event_{i}",
        )
        ids.append(node.node_id)
    return ids


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------


class MockLLM:
    """A mock LLM adapter that returns configurable JSON responses."""

    def __init__(self, responses: list[str] | None = None):
        self._responses = responses or []
        self._call_count = 0

    def complete(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        response_format: str | None = None,
    ) -> str:
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
        else:
            resp = '{"action": "wait"}'
        self._call_count += 1
        return resp

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    @property
    def supports_embeddings(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return "mock"


@pytest.fixture
def mock_llm() -> MockLLM:
    return MockLLM()
