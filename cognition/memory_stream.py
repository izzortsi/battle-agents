"""Memory stream — append-only storage of MemoryNodes.

Implements the Park et al. generative agents memory architecture:
each observation, reflection, and plan is stored as a MemoryNode with
timestamp, importance (poignancy), SPO triple, optional embedding, and
provenance links to supporting evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MemoryType(str, Enum):
    OBSERVATION = "observation"
    REFLECTION = "reflection"
    PLAN = "plan"


@dataclass
class MemoryNode:
    """A single memory entry in an agent's memory stream."""

    node_id: int
    turn_created: int
    last_accessed: int
    memory_type: MemoryType
    description: str  # natural-language content
    poignancy: int  # 1–10 importance score
    depth: int = 0  # 0 for observations, ≥1 for reflections
    embedding: Optional[list[float]] = None

    # SPO triple for structured retrieval
    subject: str = ""
    predicate: str = ""
    object: str = ""

    # Provenance: which memories were synthesised to produce this one
    evidence_ids: list[int] = field(default_factory=list)

    def touch(self, current_turn: int) -> None:
        """Update last_accessed to the current turn (for recency scoring)."""
        self.last_accessed = current_turn

    def __repr__(self) -> str:
        return (
            f"Memory({self.node_id}, {self.memory_type.value}, "
            f"p={self.poignancy}, d={self.depth}, "
            f"'{self.description[:40]}...')"
        )


class MemoryStream:
    """Append-only list of MemoryNodes for one agent.

    Provides indexing helpers for type filtering, recency, and
    importance accumulation (used to trigger reflections).
    """

    def __init__(self) -> None:
        self._nodes: list[MemoryNode] = []
        self._next_id: int = 0
        self.importance_accumulator: float = (
            0.0  # sum of poignancy since last reflection
        )

    # -- Append ----------------------------------------------------------------

    def add(
        self,
        turn: int,
        memory_type: MemoryType,
        description: str,
        poignancy: int,
        depth: int = 0,
        embedding: Optional[list[float]] = None,
        subject: str = "",
        predicate: str = "",
        object_: str = "",
        evidence_ids: Optional[list[int]] = None,
    ) -> MemoryNode:
        """Create and store a new MemoryNode.  Returns the node."""
        node = MemoryNode(
            node_id=self._next_id,
            turn_created=turn,
            last_accessed=turn,
            memory_type=memory_type,
            description=description,
            poignancy=poignancy,
            depth=depth,
            embedding=embedding,
            subject=subject,
            predicate=predicate,
            object=object_,
            evidence_ids=evidence_ids or [],
        )
        self._nodes.append(node)
        self._next_id += 1
        self.importance_accumulator += poignancy
        return node

    # -- Queries ---------------------------------------------------------------

    def get(self, node_id: int) -> MemoryNode | None:
        """Retrieve a node by ID (O(1) since IDs are sequential indices)."""
        if 0 <= node_id < len(self._nodes):
            return self._nodes[node_id]
        return None

    def all(self) -> list[MemoryNode]:
        return list(self._nodes)

    def get_by_type(self, memory_type: MemoryType) -> list[MemoryNode]:
        return [n for n in self._nodes if n.memory_type == memory_type]

    def get_recent(self, k: int) -> list[MemoryNode]:
        """Return the k most recently created nodes."""
        return list(self._nodes[-k:])

    def get_since(self, turn: int) -> list[MemoryNode]:
        """Return all nodes created on or after `turn`."""
        return [n for n in self._nodes if n.turn_created >= turn]

    # -- Importance accumulator ------------------------------------------------

    def reset_importance(self) -> float:
        """Reset and return the accumulated importance (for reflection trigger)."""
        val = self.importance_accumulator
        self.importance_accumulator = 0.0
        return val

    @property
    def should_reflect(self, threshold: float = 50.0) -> bool:
        return self.importance_accumulator >= threshold

    # -- Misc ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._nodes)

    def __bool__(self) -> bool:
        return bool(self._nodes)
