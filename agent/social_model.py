"""Social model — per-agent relationship tracking.

Each agent maintains a SocialModel that maps other agents to Relationship
objects.  Dispositions evolve through heuristic updates (attacks, heals,
kills) and LLM-driven dialogue self-reports.

The environment's alliance_resolver infers alliance status from the
social models of each pair of agents.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class Relationship:
    """One agent's view of another agent."""

    agent_id: str
    agent_name: str
    disposition: float = 0.0  # -1.0 (hostile) to +1.0 (allied)
    trust: float = 0.5  # 0.0 (no trust) to 1.0 (full trust)
    interaction_count: int = 0
    last_interaction_turn: int = 0
    alliance_declared: bool = False
    alliance_turn: Optional[int] = None
    betrayal_count: int = 0
    notes: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"Rel({self.agent_name}: disp={self.disposition:+.2f}, "
            f"trust={self.trust:.2f}, interactions={self.interaction_count})"
        )


class SocialModel:
    """Tracks one agent's relationships with all other agents."""

    def __init__(self, owner_id: str) -> None:
        self.owner_id = owner_id
        self._relationships: dict[str, Relationship] = {}

    def ensure_relationship(self, agent_id: str, agent_name: str) -> Relationship:
        """Get or create a relationship with the given agent."""
        if agent_id not in self._relationships:
            self._relationships[agent_id] = Relationship(
                agent_id=agent_id, agent_name=agent_name
            )
        return self._relationships[agent_id]

    def get_relationship(self, agent_id: str) -> Relationship | None:
        return self._relationships.get(agent_id)

    def get_disposition(self, agent_id: str) -> float:
        """Get disposition toward an agent (0.0 if no relationship exists)."""
        rel = self._relationships.get(agent_id)
        return rel.disposition if rel else 0.0

    def update_disposition(
        self,
        agent_id: str,
        delta: float,
        reason: str,
        turn: int = 0,
        agent_name: str = "",
    ) -> float:
        """Shift disposition toward an agent by delta, clamped to [-1, 1].

        Returns the new disposition value.
        """
        rel = self.ensure_relationship(agent_id, agent_name)
        old = rel.disposition
        rel.disposition = max(-1.0, min(1.0, rel.disposition + delta))
        rel.interaction_count += 1
        if turn > 0:
            rel.last_interaction_turn = turn
        if reason:
            rel.notes.append(f"[turn {turn}] {reason} (Δ{delta:+.2f})")
        log.debug(
            f"  Social: {self.owner_id} -> {agent_id} disposition "
            f"{old:+.2f} -> {rel.disposition:+.2f} ({reason})"
        )
        return rel.disposition

    def update_trust(self, agent_id: str, delta: float, agent_name: str = "") -> float:
        """Shift trust toward an agent by delta, clamped to [0, 1]."""
        rel = self.ensure_relationship(agent_id, agent_name)
        rel.trust = max(0.0, min(1.0, rel.trust + delta))
        return rel.trust

    def record_betrayal(self, agent_id: str, turn: int, agent_name: str = "") -> None:
        """Record a betrayal by this agent."""
        rel = self.ensure_relationship(agent_id, agent_name)
        rel.betrayal_count += 1
        rel.alliance_declared = False
        rel.notes.append(f"[turn {turn}] BETRAYAL")

    def declare_alliance(self, agent_id: str, turn: int, agent_name: str = "") -> None:
        """Record that an alliance has been verbally declared."""
        rel = self.ensure_relationship(agent_id, agent_name)
        rel.alliance_declared = True
        rel.alliance_turn = turn
        rel.notes.append(f"[turn {turn}] Alliance declared")

    def get_allies(self, threshold: float = 0.5) -> list[str]:
        """Return agent_ids with disposition above threshold."""
        return [
            aid
            for aid, rel in self._relationships.items()
            if rel.disposition > threshold
        ]

    def get_enemies(self, threshold: float = -0.3) -> list[str]:
        """Return agent_ids with disposition below threshold."""
        return [
            aid
            for aid, rel in self._relationships.items()
            if rel.disposition < threshold
        ]

    def all_relationships(self) -> dict[str, Relationship]:
        return dict(self._relationships)

    def summary(self) -> str:
        """Return a human-readable summary of all relationships."""
        if not self._relationships:
            return "No relationships."
        lines = []
        for rel in self._relationships.values():
            status = (
                "ally"
                if rel.disposition > 0.5
                else ("enemy" if rel.disposition < -0.3 else "neutral")
            )
            lines.append(
                f"  {rel.agent_name}: {rel.disposition:+.2f} ({status}), "
                f"trust={rel.trust:.2f}"
            )
        return "\n".join(lines)

    # -- Heuristic disposition updates from combat events ---------------------

    def on_attacked_by(
        self, attacker_id: str, turn: int, damage: int, agent_name: str = ""
    ) -> None:
        """Someone attacked us. Large negative shift."""
        # -0.3 to -0.5 based on damage severity
        delta = -0.3 - min(0.2, damage / 100.0)
        self.update_disposition(
            attacker_id,
            delta,
            f"attacked me for {damage} damage",
            turn,
            agent_name,
        )
        self.update_trust(attacker_id, -0.2, agent_name)

    def on_healed_by(
        self, healer_id: str, turn: int, amount: int, agent_name: str = ""
    ) -> None:
        """Someone healed/buffed us. Positive shift."""
        delta = 0.2 + min(0.2, amount / 50.0)
        self.update_disposition(
            healer_id, delta, f"healed me for {amount}", turn, agent_name
        )
        self.update_trust(healer_id, 0.15, agent_name)

    def on_ally_killed(
        self, killer_id: str, ally_id: str, turn: int, agent_name: str = ""
    ) -> None:
        """Someone killed our ally."""
        self.update_disposition(
            killer_id, -0.2, f"killed my ally {ally_id}", turn, agent_name
        )

    def on_enemy_killed(
        self, killer_id: str, enemy_id: str, turn: int, agent_name: str = ""
    ) -> None:
        """Someone killed our enemy. Small positive shift."""
        self.update_disposition(
            killer_id, 0.15, f"killed my enemy {enemy_id}", turn, agent_name
        )

    def on_attacked_ally(
        self, attacker_id: str, ally_id: str, turn: int, agent_name: str = ""
    ) -> None:
        """We observed someone attacking our ally — betrayal if they were allied."""
        rel = self.get_relationship(attacker_id)
        if rel and rel.alliance_declared:
            self.record_betrayal(attacker_id, turn, agent_name)
            self.update_disposition(
                attacker_id,
                -0.6,
                "betrayed alliance by attacking ally",
                turn,
                agent_name,
            )
        else:
            self.update_disposition(
                attacker_id, -0.15, f"attacked my ally {ally_id}", turn, agent_name
            )
