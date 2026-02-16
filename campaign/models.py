"""Campaign data models — pure dataclasses, no I/O.

These represent the persistent state of a campaign.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class CampaignMeta:
    """Top-level campaign metadata."""

    campaign_id: int = 0
    name: str = "Unnamed Campaign"
    created_at: str = ""  # ISO-8601
    battle_count: int = 0  # battles completed so far

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


@dataclass
class RosterEntry:
    """One character in a campaign roster — persistent state between battles."""

    agent_id: str
    name: str
    combat_class: str = "warrior"
    sprite: str = ""
    backstory: str = ""
    personality_traits: list[str] = field(default_factory=list)

    # Progression
    xp: int = 0
    level: int = 1

    # Base stats (grow on level-up)
    atk: int = 10
    mgk: int = 10
    spd: int = 10
    con: int = 10
    hit: int = 10
    attack_range: int = 1

    # Abilities (serialised as list of dicts)
    abilities: list[dict] = field(default_factory=list)

    # Moral alignment (persisted across battles, drifts in-battle)
    morality: float = 0.0  # -1.0 evil … +1.0 good
    order_value: float = 0.0  # -1.0 chaotic … +1.0 lawful

    # Campaign state
    alive: bool = True  # always True — kept for schema compatibility

    @property
    def xp_to_next_level(self) -> int:
        """XP required to reach the next level."""
        return self.level * 100

    @property
    def xp_progress(self) -> float:
        """Fraction of XP toward next level (0.0–1.0)."""
        threshold = self.xp_to_next_level
        return min(1.0, self.xp / threshold) if threshold > 0 else 1.0

    def can_level_up(self) -> bool:
        return self.xp >= self.xp_to_next_level

    def apply_level_up(self, stat_increases: dict[str, int]) -> None:
        """Apply stat increases from a level-up.

        *stat_increases* maps stat names (``"atk"``, ``"mgk"``, etc.) to
        integer increments.  XP is reduced by the threshold and level
        increments by one.
        """
        self.xp -= self.xp_to_next_level
        self.level += 1
        for stat, delta in stat_increases.items():
            if hasattr(self, stat) and stat in ("atk", "mgk", "spd", "con", "hit"):
                current = getattr(self, stat)
                setattr(self, stat, min(30, current + delta))  # soft cap 30


@dataclass
class BattleRecord:
    """Result of a single campaign battle."""

    battle_num: int
    winner_ids: list[str] = field(default_factory=list)
    death_ids: list[str] = field(default_factory=list)
    rounds: int = 0
    timestamp: str = ""
    xp_awards: dict[str, int] = field(default_factory=dict)  # agent_id -> xp gained

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class SerializedMemory:
    """A compressed memory for carry-over between battles."""

    agent_id: str
    description: str
    poignancy: int
    memory_type: str  # "observation", "reflection", "plan"
    turn_created: int


@dataclass
class SerializedRelationship:
    """A serialised relationship for carry-over between battles."""

    owner_id: str
    target_id: str
    target_name: str
    disposition: float
    trust: float
    betrayal_count: int
    alliance_declared: bool
