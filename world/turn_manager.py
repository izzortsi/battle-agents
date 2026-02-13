"""Turn manager — initiative rolling, turn ordering, round tracking.

Phase 1: simple round-robin by speed (descending).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.agent import Agent


@dataclass
class TurnManager:
    """Manages initiative order and round progression."""

    round_number: int = 0
    _order: list[str] = field(default_factory=list)
    _current_idx: int = 0

    def roll_initiative(self, agents: list[Agent]) -> list[str]:
        """Determine turn order.  Sorted by speed descending, ties broken randomly."""
        shuffled = list(agents)
        random.shuffle(shuffled)  # randomize before stable sort for tie-breaking
        shuffled.sort(key=lambda a: a.attributes.speed, reverse=True)
        self._order = [a.agent_id for a in shuffled]
        self._current_idx = 0
        self.round_number = 1
        return list(self._order)

    @property
    def current_agent_id(self) -> str | None:
        if not self._order:
            return None
        return self._order[self._current_idx]

    @property
    def turn_order(self) -> list[str]:
        return list(self._order)

    def advance(self) -> str | None:
        """Advance to the next agent.  Returns the new current agent id,
        or None if the round is over (will auto-advance to next round)."""
        if not self._order:
            return None
        self._current_idx += 1
        if self._current_idx >= len(self._order):
            self._current_idx = 0
            self.round_number += 1
        return self._order[self._current_idx]

    def remove_agent(self, agent_id: str) -> None:
        """Remove a dead agent from the turn order."""
        if agent_id not in self._order:
            return
        idx = self._order.index(agent_id)
        self._order.remove(agent_id)
        if not self._order:
            return
        # Adjust current index if needed
        if idx < self._current_idx:
            self._current_idx -= 1
        elif idx == self._current_idx:
            # Current agent died (mid-turn removal)
            if self._current_idx >= len(self._order):
                self._current_idx = 0
                self.round_number += 1
        # Clamp
        self._current_idx = min(self._current_idx, len(self._order) - 1)

    @property
    def global_turn(self) -> int:
        """A monotonically increasing turn counter across all rounds."""
        if not self._order:
            return 0
        return (self.round_number - 1) * len(self._order) + self._current_idx + 1
