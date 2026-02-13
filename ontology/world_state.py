"""WorldState — the single source of truth.

Wraps a RelationStore and provides high-level accessors.
Agents never read this directly; they receive perceptions filtered through
the perception engine.
"""

from __future__ import annotations

from ontology.relations import RelationInstance, RelationStore


class WorldState:
    """Ground instantiation of all relations R — the god-view of reality."""

    def __init__(self, store: RelationStore | None = None) -> None:
        self._store = store or RelationStore()

    @property
    def store(self) -> RelationStore:
        return self._store

    # -- Convenience accessors ------------------------------------------------

    def set_position(self, agent_id: str, tile: str) -> None:
        """Move agent to tile, removing any previous position."""
        old = self._store.query("occupies", arg0=agent_id)
        for tup in old:
            self._store.remove("occupies", *tup)
        self._store.add("occupies", agent_id, tile)

    def get_position(self, agent_id: str) -> str | None:
        results = self._store.query("occupies", arg0=agent_id)
        return results[0][1] if results else None

    def agents_at(self, tile: str) -> list[str]:
        results = self._store.query("occupies", arg1=tile)
        return [t[0] for t in results]

    def add_status(self, agent_id: str, status: str) -> None:
        self._store.add("has_status", agent_id, status)

    def remove_status(self, agent_id: str, status: str) -> None:
        self._store.remove("has_status", agent_id, status)

    def get_statuses(self, agent_id: str) -> list[str]:
        results = self._store.query("has_status", arg0=agent_id)
        return [t[1] for t in results]

    def set_holding(self, agent_id: str, object_id: str) -> None:
        self._store.add("holds", agent_id, object_id)

    def get_held(self, agent_id: str) -> list[str]:
        results = self._store.query("holds", arg0=agent_id)
        return [t[1] for t in results]

    def record_event(self, event_id: str, turn: int) -> None:
        self._store.add("occurred", event_id, str(turn))

    def add_disposition(self, agent_a: str, agent_b: str, disp: str) -> None:
        # Remove old disposition first
        old = self._store.query("has_disposition", arg0=agent_a, arg1=agent_b)
        for tup in old:
            self._store.remove("has_disposition", *tup)
        self._store.add("has_disposition", agent_a, agent_b, disp)

    def get_disposition(self, agent_a: str, agent_b: str) -> str | None:
        results = self._store.query("has_disposition", arg0=agent_a, arg1=agent_b)
        return results[0][2] if results else None

    # -- Bulk accessors -------------------------------------------------------

    def all_facts(self) -> list[RelationInstance]:
        return self._store.all_facts()

    def facts_about(self, entity_id: str) -> list[RelationInstance]:
        return self._store.query_entity(entity_id)

    def snapshot(self) -> "WorldState":
        """Return an independent copy of the current state."""
        return WorldState(self._store.copy())

    def __len__(self) -> int:
        return len(self._store)
