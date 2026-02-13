"""AgentKnowledge — a partial, possibly incorrect view of the world.

K_a ⊆ P(R): what agent a believes to be true.  This can diverge from the
ground truth in WorldState — that divergence is the mechanism for surprise,
misinformation, and dramatic irony.
"""

from __future__ import annotations

from ontology.relations import RelationInstance, RelationStore


class AgentKnowledge:
    """An agent's subjective belief store.

    Structurally identical to a RelationStore, but semantically different:
    facts here are *believed* by the agent, not necessarily true.
    """

    def __init__(self, store: RelationStore | None = None) -> None:
        self._store = store or RelationStore()

    @property
    def store(self) -> RelationStore:
        return self._store

    def believe(self, relation: str, *args: str) -> RelationInstance:
        """Record that the agent believes this fact."""
        return self._store.add(relation, *args)

    def unbelieve(self, relation: str, *args: str) -> bool:
        """Remove a belief."""
        return self._store.remove(relation, *args)

    def believes(self, relation: str, *args: str) -> bool:
        """Check if the agent holds a particular belief."""
        return self._store.has(relation, *args)

    def beliefs_about(self, entity_id: str) -> list[RelationInstance]:
        """All beliefs involving a given entity."""
        return self._store.query_entity(entity_id)

    def all_beliefs(self) -> list[RelationInstance]:
        return self._store.all_facts()

    def update_from_perceptions(
        self, perceived_facts: list[RelationInstance]
    ) -> list[RelationInstance]:
        """Incorporate new perceptions.  Returns the list of *new* facts
        (facts the agent did not previously believe)."""
        new: list[RelationInstance] = []
        for fact in perceived_facts:
            if not self._store.has(fact.relation, *fact.args):
                self._store.add(fact.relation, *fact.args)
                new.append(fact)
        return new

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
