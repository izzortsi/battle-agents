"""Relation registry and ground instantiation.

A Relation is a named predicate of fixed arity over domain entities.
A RelationInstance (ground fact) is a concrete tuple of entity ids.
The RelationStore holds all ground facts and supports add/remove/query.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Optional


@dataclass(frozen=True)
class RelationSchema:
    """Declares a relation name and its arity."""

    name: str
    arity: int
    arg_names: tuple[str, ...] = ()  # human-readable slot names

    def __post_init__(self) -> None:
        if self.arg_names and len(self.arg_names) != self.arity:
            raise ValueError(
                f"arg_names length {len(self.arg_names)} != arity {self.arity}"
            )


@dataclass(frozen=True)
class RelationInstance:
    """A ground fact: relation_name(arg0, arg1, ...)."""

    relation: str
    args: tuple[str, ...]

    def __str__(self) -> str:
        return f"{self.relation}({', '.join(self.args)})"


class RelationStore:
    """Stores ground facts and supports indexed queries.

    Internal index: relation_name -> set of arg tuples.
    Secondary index: arg_value -> set of (relation_name, arg_tuple) for fast
    entity-centric queries.
    """

    def __init__(self) -> None:
        self._schemas: dict[str, RelationSchema] = {}
        # relation_name -> set of arg tuples
        self._facts: dict[str, set[tuple[str, ...]]] = {}
        # entity_id -> set of RelationInstance
        self._entity_index: dict[str, set[RelationInstance]] = {}

    # -- Schema registration --------------------------------------------------

    def register(self, schema: RelationSchema) -> None:
        self._schemas[schema.name] = schema
        self._facts.setdefault(schema.name, set())

    def get_schema(self, name: str) -> Optional[RelationSchema]:
        return self._schemas.get(name)

    # -- Fact manipulation -----------------------------------------------------

    def add(self, relation: str, *args: str) -> RelationInstance:
        schema = self._schemas.get(relation)
        if schema and len(args) != schema.arity:
            raise ValueError(f"{relation} expects {schema.arity} args, got {len(args)}")
        tup = tuple(args)
        self._facts.setdefault(relation, set()).add(tup)
        inst = RelationInstance(relation, tup)
        for a in args:
            self._entity_index.setdefault(a, set()).add(inst)
        return inst

    def remove(self, relation: str, *args: str) -> bool:
        tup = tuple(args)
        bucket = self._facts.get(relation)
        if bucket is None or tup not in bucket:
            return False
        bucket.discard(tup)
        inst = RelationInstance(relation, tup)
        for a in args:
            idx = self._entity_index.get(a)
            if idx:
                idx.discard(inst)
        return True

    def has(self, relation: str, *args: str) -> bool:
        bucket = self._facts.get(relation)
        return bucket is not None and tuple(args) in bucket

    # -- Queries ---------------------------------------------------------------

    def query(self, relation: str, **bindings: str) -> list[tuple[str, ...]]:
        """Query facts for a relation with optional positional bindings.

        Example: store.query("occupies", arg0="kael") returns all tuples
        where the first argument is "kael".
        """
        bucket = self._facts.get(relation)
        if bucket is None:
            return []
        schema = self._schemas.get(relation)
        results: list[tuple[str, ...]] = []
        for tup in bucket:
            match = True
            for key, val in bindings.items():
                if key.startswith("arg"):
                    idx = int(key[3:])
                    if idx >= len(tup) or tup[idx] != val:
                        match = False
                        break
                elif schema and schema.arg_names:
                    try:
                        idx = schema.arg_names.index(key)
                    except ValueError:
                        match = False
                        break
                    if tup[idx] != val:
                        match = False
                        break
            if match:
                results.append(tup)
        return results

    def query_entity(self, entity_id: str) -> list[RelationInstance]:
        """All facts involving a given entity."""
        return list(self._entity_index.get(entity_id, set()))

    def all_facts(self, relation: Optional[str] = None) -> list[RelationInstance]:
        """All ground facts, optionally filtered by relation name."""
        result: list[RelationInstance] = []
        rels = [relation] if relation else list(self._facts.keys())
        for r in rels:
            for tup in self._facts.get(r, set()):
                result.append(RelationInstance(r, tup))
        return result

    def clear(self, relation: Optional[str] = None) -> None:
        if relation:
            for tup in list(self._facts.get(relation, set())):
                self.remove(relation, *tup)
        else:
            self._facts.clear()
            self._entity_index.clear()

    def __len__(self) -> int:
        return sum(len(v) for v in self._facts.values())

    def copy(self) -> "RelationStore":
        """Deep copy of the store."""
        new = RelationStore()
        for s in self._schemas.values():
            new.register(s)
        for rel, tuples in self._facts.items():
            for tup in tuples:
                new.add(rel, *tup)
        return new
