"""Tests for the ontology layer: domain entities, relations, world state, knowledge."""

from __future__ import annotations

import pytest

from ontology.domain import (
    ActionEntity,
    AgentEntity,
    Entity,
    EntityType,
    EventEntity,
    LocationEntity,
    ObjectEntity,
)
from ontology.relations import RelationInstance, RelationSchema, RelationStore
from ontology.world_state import WorldState
from ontology.knowledge import AgentKnowledge


# ---------------------------------------------------------------------------
# Domain entities
# ---------------------------------------------------------------------------


class TestEntity:
    def test_agent_entity_type(self):
        e = AgentEntity(entity_id="kael")
        assert e.entity_type == EntityType.AGENT

    def test_location_entity_type(self):
        e = LocationEntity(entity_id="tile_3_5")
        assert e.entity_type == EntityType.LOCATION

    def test_object_entity_type(self):
        e = ObjectEntity(entity_id="sword")
        assert e.entity_type == EntityType.OBJECT

    def test_event_entity_type(self):
        e = EventEntity(entity_id="explosion")
        assert e.entity_type == EntityType.EVENT

    def test_action_entity_type(self):
        e = ActionEntity(entity_id="attack")
        assert e.entity_type == EntityType.ACTION

    def test_entity_is_frozen(self):
        e = AgentEntity(entity_id="kael")
        with pytest.raises(AttributeError):
            e.entity_id = "lyra"  # type: ignore[misc]

    def test_entity_is_hashable(self):
        a = AgentEntity(entity_id="kael")
        b = AgentEntity(entity_id="lyra")
        s = {a, b}
        assert len(s) == 2
        assert a in s

    def test_entity_str(self):
        e = AgentEntity(entity_id="kael")
        assert str(e) == "kael"

    def test_entity_equality(self):
        a = AgentEntity(entity_id="kael")
        b = AgentEntity(entity_id="kael")
        assert a == b

    def test_entity_inequality(self):
        a = AgentEntity(entity_id="kael")
        b = AgentEntity(entity_id="lyra")
        assert a != b


# ---------------------------------------------------------------------------
# Relation schemas
# ---------------------------------------------------------------------------


class TestRelationSchema:
    def test_basic_schema(self):
        s = RelationSchema("occupies", 2)
        assert s.name == "occupies"
        assert s.arity == 2

    def test_schema_with_arg_names(self):
        s = RelationSchema("occupies", 2, ("agent", "tile"))
        assert s.arg_names == ("agent", "tile")

    def test_schema_arg_names_length_mismatch(self):
        with pytest.raises(ValueError, match="arg_names length"):
            RelationSchema("occupies", 2, ("agent",))

    def test_schema_is_frozen(self):
        s = RelationSchema("occupies", 2)
        with pytest.raises(AttributeError):
            s.name = "other"  # type: ignore[misc]


class TestRelationInstance:
    def test_str_representation(self):
        inst = RelationInstance("occupies", ("kael", "3_5"))
        assert str(inst) == "occupies(kael, 3_5)"

    def test_is_frozen(self):
        inst = RelationInstance("occupies", ("kael", "3_5"))
        with pytest.raises(AttributeError):
            inst.relation = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Relation store
# ---------------------------------------------------------------------------


class TestRelationStore:
    def test_register_and_add(self, relation_store: RelationStore):
        inst = relation_store.add("occupies", "kael", "3_5")
        assert inst.relation == "occupies"
        assert inst.args == ("kael", "3_5")

    def test_add_arity_mismatch(self, relation_store: RelationStore):
        with pytest.raises(ValueError):
            relation_store.add("occupies", "kael")  # expects 2 args

    def test_has(self, relation_store: RelationStore):
        relation_store.add("occupies", "kael", "3_5")
        assert relation_store.has("occupies", "kael", "3_5")
        assert not relation_store.has("occupies", "kael", "4_5")

    def test_remove(self, relation_store: RelationStore):
        relation_store.add("occupies", "kael", "3_5")
        assert relation_store.remove("occupies", "kael", "3_5")
        assert not relation_store.has("occupies", "kael", "3_5")

    def test_remove_nonexistent(self, relation_store: RelationStore):
        assert not relation_store.remove("occupies", "kael", "99_99")

    def test_query_positional(self, relation_store: RelationStore):
        relation_store.add("occupies", "kael", "3_5")
        relation_store.add("occupies", "lyra", "4_5")
        results = relation_store.query("occupies", arg0="kael")
        assert len(results) == 1
        assert results[0] == ("kael", "3_5")

    def test_query_named_bindings(self, relation_store: RelationStore):
        relation_store.add("occupies", "kael", "3_5")
        results = relation_store.query("occupies", tile="3_5")
        assert len(results) == 1

    def test_query_entity(self, relation_store: RelationStore):
        relation_store.add("occupies", "kael", "3_5")
        relation_store.add("has_status", "kael", "poisoned")
        facts = relation_store.query_entity("kael")
        assert len(facts) == 2

    def test_all_facts(self, relation_store: RelationStore):
        relation_store.add("occupies", "kael", "3_5")
        relation_store.add("has_status", "kael", "poisoned")
        facts = relation_store.all_facts()
        assert len(facts) == 2

    def test_all_facts_filtered(self, relation_store: RelationStore):
        relation_store.add("occupies", "kael", "3_5")
        relation_store.add("has_status", "kael", "poisoned")
        facts = relation_store.all_facts("occupies")
        assert len(facts) == 1

    def test_len(self, relation_store: RelationStore):
        assert len(relation_store) == 0
        relation_store.add("occupies", "kael", "3_5")
        assert len(relation_store) == 1

    def test_clear_all(self, relation_store: RelationStore):
        relation_store.add("occupies", "kael", "3_5")
        relation_store.add("has_status", "kael", "poisoned")
        relation_store.clear()
        assert len(relation_store) == 0

    def test_clear_specific_relation(self, relation_store: RelationStore):
        relation_store.add("occupies", "kael", "3_5")
        relation_store.add("has_status", "kael", "poisoned")
        relation_store.clear("occupies")
        assert len(relation_store) == 1
        assert relation_store.has("has_status", "kael", "poisoned")

    def test_copy_is_independent(self, relation_store: RelationStore):
        relation_store.add("occupies", "kael", "3_5")
        copy = relation_store.copy()
        relation_store.add("occupies", "lyra", "4_5")
        assert len(copy) == 1
        assert len(relation_store) == 2

    def test_query_empty_store(self, relation_store: RelationStore):
        results = relation_store.query("occupies", arg0="kael")
        assert results == []

    def test_add_without_schema(self):
        """Adding a fact for an unregistered relation (no schema) should work."""
        store = RelationStore()
        inst = store.add("custom", "a", "b")
        assert inst.relation == "custom"
        assert store.has("custom", "a", "b")


# ---------------------------------------------------------------------------
# World state
# ---------------------------------------------------------------------------


class TestWorldState:
    def test_set_and_get_position(self, world_state: WorldState):
        world_state.set_position("kael", "3_5")
        assert world_state.get_position("kael") == "3_5"

    def test_position_update_removes_old(self, world_state: WorldState):
        world_state.set_position("kael", "3_5")
        world_state.set_position("kael", "4_5")
        assert world_state.get_position("kael") == "4_5"
        # Old position no longer occupied by kael
        assert "kael" not in world_state.agents_at("3_5")

    def test_get_position_missing(self, world_state: WorldState):
        assert world_state.get_position("nobody") is None

    def test_agents_at(self, world_state: WorldState):
        world_state.set_position("kael", "3_5")
        world_state.set_position("lyra", "3_5")
        agents = world_state.agents_at("3_5")
        assert set(agents) == {"kael", "lyra"}

    def test_status_effects(self, world_state: WorldState):
        world_state.add_status("kael", "poisoned")
        assert "poisoned" in world_state.get_statuses("kael")
        world_state.remove_status("kael", "poisoned")
        assert "poisoned" not in world_state.get_statuses("kael")

    def test_holding(self, world_state: WorldState):
        world_state.set_holding("kael", "sword")
        assert "sword" in world_state.get_held("kael")

    def test_disposition_overwrite(self, world_state: WorldState):
        world_state.add_disposition("kael", "lyra", "friendly")
        world_state.add_disposition("kael", "lyra", "hostile")
        assert world_state.get_disposition("kael", "lyra") == "hostile"

    def test_disposition_missing(self, world_state: WorldState):
        assert world_state.get_disposition("kael", "lyra") is None

    def test_record_event(self, world_state: WorldState):
        world_state.record_event("explosion_1", 5)
        facts = world_state.facts_about("explosion_1")
        assert len(facts) == 1

    def test_snapshot_independence(self, world_state: WorldState):
        world_state.set_position("kael", "3_5")
        snap = world_state.snapshot()
        world_state.set_position("kael", "9_9")
        assert snap.get_position("kael") == "3_5"
        assert world_state.get_position("kael") == "9_9"

    def test_len(self, world_state: WorldState):
        assert len(world_state) == 0
        world_state.set_position("kael", "3_5")
        assert len(world_state) == 1


# ---------------------------------------------------------------------------
# Agent knowledge
# ---------------------------------------------------------------------------


class TestAgentKnowledge:
    def test_believe_and_query(self):
        k = AgentKnowledge()
        k.believe("occupies", "kael", "3_5")
        assert k.believes("occupies", "kael", "3_5")

    def test_unbelieve(self):
        k = AgentKnowledge()
        k.believe("occupies", "kael", "3_5")
        assert k.unbelieve("occupies", "kael", "3_5")
        assert not k.believes("occupies", "kael", "3_5")

    def test_beliefs_about(self):
        k = AgentKnowledge()
        k.believe("occupies", "kael", "3_5")
        k.believe("has_status", "kael", "poisoned")
        assert len(k.beliefs_about("kael")) == 2

    def test_update_from_perceptions_returns_new(self):
        k = AgentKnowledge()
        k.believe("occupies", "kael", "3_5")
        perceptions = [
            RelationInstance("occupies", ("kael", "3_5")),  # existing
            RelationInstance("has_status", ("kael", "poisoned")),  # new
        ]
        new = k.update_from_perceptions(perceptions)
        assert len(new) == 1
        assert new[0].relation == "has_status"

    def test_clear(self):
        k = AgentKnowledge()
        k.believe("occupies", "kael", "3_5")
        k.clear()
        assert len(k) == 0

    def test_len(self):
        k = AgentKnowledge()
        assert len(k) == 0
        k.believe("occupies", "kael", "3_5")
        assert len(k) == 1
