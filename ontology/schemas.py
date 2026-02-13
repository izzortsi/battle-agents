"""Concrete relation schemas for the combat game.

Registers all relation schemas used by the system.
Call `register_all(store)` to populate a RelationStore with schemas.
"""

from __future__ import annotations

from ontology.relations import RelationSchema, RelationStore

# -- Schema definitions --------------------------------------------------------

OCCUPIES = RelationSchema("occupies", 2, ("agent", "location"))
CONTAINS = RelationSchema("contains", 2, ("location", "object"))
HAS_DISPOSITION = RelationSchema(
    "has_disposition", 3, ("agent_a", "agent_b", "disposition")
)
ALLIED_WITH = RelationSchema("allied_with", 2, ("agent_a", "agent_b"))
HAS_STATUS = RelationSchema("has_status", 2, ("agent", "status_effect"))
HOLDS = RelationSchema("holds", 2, ("agent", "object"))
OCCURRED = RelationSchema("occurred", 2, ("event", "turn"))

ALL_SCHEMAS: list[RelationSchema] = [
    OCCUPIES,
    CONTAINS,
    HAS_DISPOSITION,
    ALLIED_WITH,
    HAS_STATUS,
    HOLDS,
    OCCURRED,
]


def register_all(store: RelationStore) -> None:
    """Register all game relation schemas in the given store."""
    for schema in ALL_SCHEMAS:
        store.register(schema)


def create_store() -> RelationStore:
    """Create a new RelationStore pre-loaded with all schemas."""
    store = RelationStore()
    register_all(store)
    return store
