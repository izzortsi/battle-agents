"""D&D-style two-axis moral alignment with in-battle drift.

Axes:
  morality  -1.0 (Evil)    → +1.0 (Good)
  order     -1.0 (Chaotic) → +1.0 (Lawful)

The discrete label (e.g. "Chaotic Good") is derived from thresholds at ±0.33.
"""

from __future__ import annotations

from dataclasses import dataclass

# Threshold for mapping floats → discrete labels
_THRESHOLD = 0.33

# Canonical float values for named positions on each axis
_AXIS_VALUES = {"lawful": 0.66, "neutral": 0.0, "chaotic": -0.66}
_MORAL_VALUES = {"good": 0.66, "neutral": 0.0, "evil": -0.66}

# All 9 valid label strings (underscore-separated, lowercase)
VALID_LABELS = frozenset(
    f"{o}_{m}"
    for o in ("lawful", "neutral", "chaotic")
    for m in ("good", "neutral", "evil")
) | {"true_neutral"}

# Drift deltas for each combat event type
DRIFT_TABLE: dict[str, tuple[float, float]] = {
    # event_type: (morality_delta, order_delta)
    "attack_ally": (-0.08, 0.0),
    "heal_ally": (+0.05, 0.0),
    "aoe_hit_ally": (-0.03, -0.03),
    "betray_alliance": (-0.05, -0.10),
    "honor_alliance": (0.0, +0.03),
    "spare_low_hp": (+0.05, 0.0),
    "kill_blow": (-0.02, 0.0),
    "defend": (0.0, +0.02),
}


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


@dataclass
class MoralAlignment:
    """Mutable two-axis moral alignment."""

    morality: float = 0.0  # -1 evil … +1 good
    order: float = 0.0  # -1 chaotic … +1 lawful

    # -- Label derivation ---------------------------------------------------

    @property
    def label(self) -> str:
        """Derive the D&D alignment label from current float values."""
        if self.order > _THRESHOLD:
            o = "Lawful"
        elif self.order < -_THRESHOLD:
            o = "Chaotic"
        else:
            o = "Neutral"

        if self.morality > _THRESHOLD:
            m = "Good"
        elif self.morality < -_THRESHOLD:
            m = "Evil"
        else:
            m = "Neutral"

        if o == "Neutral" and m == "Neutral":
            return "True Neutral"
        return f"{o} {m}"

    @property
    def label_key(self) -> str:
        """Underscore-lowercase key suitable for YAML / serialisation."""
        return self.label.lower().replace(" ", "_")

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_label(cls, label: str) -> MoralAlignment:
        """Parse a label like ``'lawful_good'`` or ``'true_neutral'``.

        Accepts underscore or space separators, case-insensitive.
        Falls back to True Neutral on unrecognised input.
        """
        raw = label.strip().lower().replace(" ", "_")
        if raw == "true_neutral":
            return cls(morality=0.0, order=0.0)

        parts = raw.split("_")
        if len(parts) != 2:
            return cls(morality=0.0, order=0.0)

        order_str, moral_str = parts
        order_val = _AXIS_VALUES.get(order_str, 0.0)
        moral_val = _MORAL_VALUES.get(moral_str, 0.0)
        return cls(morality=moral_val, order=order_val)

    # -- Mutation -----------------------------------------------------------

    def shift(self, morality_delta: float = 0.0, order_delta: float = 0.0) -> None:
        """Shift axes by the given deltas, clamping to [-1, +1]."""
        self.morality = _clamp(self.morality + morality_delta)
        self.order = _clamp(self.order + order_delta)

    def apply_drift(self, event_type: str) -> None:
        """Apply a pre-defined drift from :data:`DRIFT_TABLE`."""
        deltas = DRIFT_TABLE.get(event_type)
        if deltas:
            self.shift(deltas[0], deltas[1])

    # -- Compatibility ------------------------------------------------------

    def compatibility(self, other: MoralAlignment) -> float:
        """Compute an initial disposition bias based on alignment similarity.

        Returns a float roughly in [-0.25, +0.25].

        Same moral pole → positive, opposed → negative.
        Same order pole → positive, opposed → negative.
        """
        bias = 0.0

        # Morality axis
        m_prod = self.morality * other.morality
        if m_prod > 0:
            # Same side — scale by how strongly aligned both are
            bias += 0.12 * min(abs(self.morality), abs(other.morality))
        elif m_prod < 0:
            bias -= 0.15 * min(abs(self.morality), abs(other.morality))

        # Order axis
        o_prod = self.order * other.order
        if o_prod > 0:
            bias += 0.08 * min(abs(self.order), abs(other.order))
        elif o_prod < 0:
            bias -= 0.10 * min(abs(self.order), abs(other.order))

        return _clamp(bias, -0.25, 0.25)

    # -- Serialisation ------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "morality": round(self.morality, 3),
            "order": round(self.order, 3),
            "label": self.label,
        }
