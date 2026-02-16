"""Agent identity — name, backstory, personality, combat class, moral alignment."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Identity:
    name: str
    backstory: str = ""
    personality_traits: list[str] = field(default_factory=list)
    combat_class: str = "warrior"  # warrior, mage, rogue, healer, etc.
    sprite: str = ""  # sprite preset name (e.g. "Mecha_Samus"), empty = SVG silhouette
    moral_alignment: str = "true_neutral"  # D&D label, e.g. "lawful_good"

    @property
    def summary(self) -> str:
        traits = (
            ", ".join(self.personality_traits) if self.personality_traits else "unknown"
        )
        return (
            f"{self.name} ({self.combat_class}) — {traits}.\n"
            f"Backstory: {self.backstory}"
        )
