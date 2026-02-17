"""Alliance resolver — infers alliance status from social models.

Five-tier system based on mutual disposition values:

    ALLIED    both dispositions >= 0.5   (mutual, strong bond — AoE protection)
    FRIENDLY  both dispositions >= 0.15  (mutual, soft bond — LLM discouraged from attacking)
    NEUTRAL   between thresholds
    ENEMY     either disposition <= -0.15 (unilateral)
    HOSTILE   either disposition <= -0.5  (unilateral, priority target)
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.social_model import SocialModel


class AllianceStatus(str, Enum):
    ALLIED = "allied"
    FRIENDLY = "friendly"
    NEUTRAL = "neutral"
    ENEMY = "enemy"
    HOSTILE = "hostile"

    @property
    def is_positive(self) -> bool:
        """True for ALLIED and FRIENDLY."""
        return self in (AllianceStatus.ALLIED, AllianceStatus.FRIENDLY)

    @property
    def is_negative(self) -> bool:
        """True for ENEMY and HOSTILE."""
        return self in (AllianceStatus.ENEMY, AllianceStatus.HOSTILE)


def resolve_alliance(
    social_a: SocialModel,
    social_b: SocialModel,
    agent_a_id: str,
    agent_b_id: str,
    allied_threshold: float = 0.5,
    friendly_threshold: float = 0.15,
    enemy_threshold: float = -0.15,
    hostile_threshold: float = -0.5,
) -> AllianceStatus:
    """Infer the alliance status between two agents.

    Negative statuses are unilateral (either party triggers them).
    Positive statuses require mutual consent (both parties above threshold).
    """
    disp_a_to_b = social_a.get_disposition(agent_b_id)
    disp_b_to_a = social_b.get_disposition(agent_a_id)

    # --- Negative statuses (unilateral — either party) ---
    if disp_a_to_b <= hostile_threshold or disp_b_to_a <= hostile_threshold:
        return AllianceStatus.HOSTILE

    if disp_a_to_b <= enemy_threshold or disp_b_to_a <= enemy_threshold:
        return AllianceStatus.ENEMY

    # --- Positive statuses (mutual — both parties) ---
    if disp_a_to_b >= allied_threshold and disp_b_to_a >= allied_threshold:
        return AllianceStatus.ALLIED

    if disp_a_to_b >= friendly_threshold and disp_b_to_a >= friendly_threshold:
        return AllianceStatus.FRIENDLY

    return AllianceStatus.NEUTRAL


def get_alliance_status_for_agent(
    agent_id: str,
    other_id: str,
    social_models: dict[str, SocialModel],
    allied_threshold: float = 0.5,
    friendly_threshold: float = 0.15,
    enemy_threshold: float = -0.15,
    hostile_threshold: float = -0.5,
) -> AllianceStatus:
    """Convenience: look up alliance status from a dict of social models."""
    social_a = social_models.get(agent_id)
    social_b = social_models.get(other_id)
    if social_a is None or social_b is None:
        return AllianceStatus.NEUTRAL
    return resolve_alliance(
        social_a,
        social_b,
        agent_id,
        other_id,
        allied_threshold,
        friendly_threshold,
        enemy_threshold,
        hostile_threshold,
    )
