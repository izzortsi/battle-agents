"""Agent attributes — stats, abilities, equipment, status effects."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Attributes:
    """Numeric stats for an agent.  Mutable — HP changes during combat."""

    max_hp: int = 100
    hp: int = 100
    max_mana: int = 50
    mana: int = 50
    attack: int = 15
    defense: int = 5
    speed: int = 10
    move_range: int = 3
    attack_range: int = 1  # melee = 1, ranged > 1

    # Status effect tracking
    status_effects: list[dict] = field(default_factory=list)
    # Each: {"type": str, "duration": int, "magnitude": float, "source": str}

    @property
    def is_alive(self) -> bool:
        return self.hp > 0

    def take_damage(self, amount: int) -> int:
        """Apply damage, return actual damage dealt."""
        actual = min(amount, self.hp)
        self.hp = max(0, self.hp - amount)
        return actual

    def heal(self, amount: int) -> int:
        """Heal, return actual amount healed."""
        actual = min(amount, self.max_hp - self.hp)
        self.hp = min(self.max_hp, self.hp + amount)
        return actual

    def spend_mana(self, cost: int) -> bool:
        """Spend mana if available.  Returns True if successful."""
        if self.mana < cost:
            return False
        self.mana -= cost
        return True

    def tick_status_effects(self) -> list[str]:
        """Decrement durations, remove expired effects.  Returns expired effect types."""
        expired: list[str] = []
        remaining: list[dict] = []
        for eff in self.status_effects:
            eff["duration"] -= 1
            if eff["duration"] <= 0:
                expired.append(eff["type"])
            else:
                remaining.append(eff)
        self.status_effects = remaining
        return expired

    def has_status(self, status_type: str) -> bool:
        return any(e["type"] == status_type for e in self.status_effects)

    def get_effective_defense(self) -> int:
        """Defense including defend status buff."""
        bonus = sum(
            e["magnitude"] for e in self.status_effects if e["type"] == "defend"
        )
        return int(self.defense + self.defense * bonus)
