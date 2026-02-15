"""Memory compression — top-K carry-over between campaign battles.

After each battle, each agent's MemoryStream is compressed down to
the *top_k* most important memories (by poignancy), which are then
persisted to the campaign database and restored before the next battle.
"""

from __future__ import annotations

from campaign.models import SerializedMemory
from cognition.memory_stream import MemoryNode, MemoryStream, MemoryType


def compress_memories(
    agent_id: str,
    stream: MemoryStream,
    top_k: int = 20,
) -> list[SerializedMemory]:
    """Extract the *top_k* most important memories from a MemoryStream.

    Returns a list of ``SerializedMemory`` ready for persistence.
    Reflections are given priority over raw observations.
    """
    nodes = stream.all()
    if not nodes:
        return []

    # Sort by (depth descending, poignancy descending) so reflections
    # and high-importance memories come first.
    ranked = sorted(nodes, key=lambda n: (n.depth, n.poignancy), reverse=True)
    selected = ranked[:top_k]

    return [
        SerializedMemory(
            agent_id=agent_id,
            description=n.description,
            poignancy=n.poignancy,
            memory_type=n.memory_type.value,
            turn_created=n.turn_created,
        )
        for n in selected
    ]


def restore_memories(
    stream: MemoryStream,
    memories: list[SerializedMemory],
    turn_offset: int = 0,
) -> None:
    """Load compressed memories back into a MemoryStream.

    Memories are added at turn 0 (or *turn_offset*) so they appear
    as "prior knowledge" in the agent's memory. The importance
    accumulator is NOT affected to avoid spurious reflection triggers.
    """
    for m in memories:
        mem_type = MemoryType(m.memory_type)
        depth = 1 if mem_type == MemoryType.REFLECTION else 0
        stream.add(
            turn=turn_offset,
            memory_type=mem_type,
            description=m.description,
            poignancy=m.poignancy,
            depth=depth,
        )
    # Reset accumulator so carried memories don't trigger immediate reflection.
    stream.importance_accumulator = 0.0
