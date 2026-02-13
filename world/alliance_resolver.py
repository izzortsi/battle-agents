"""Alliance resolver — infers alliance status from social models.

Alliances are emergent, not mechanical.  The environment infers status
from the disposition values in each agent's social model:

    ALLIED   if both dispositions > τ+  (mutual consent)
    HOSTILE  if either disposition < τ-  (unilateral)
    NEUTRAL  otherwise
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.social_model import SocialModel


class AllianceStatus(str, Enum):
    ALLIED = "allied"
    NEUTRAL = "neutral"
    HOSTILE = "hostile"


def resolve_alliance(
    social_a: SocialModel,
    social_b: SocialModel,
    agent_a_id: str,
    agent_b_id: str,
    allied_threshold: float = 0.5,
    hostile_threshold: float = -0.3,
) -> AllianceStatus:
    """Infer the alliance status between two agents.

    ALLIED requires mutual high disposition (both > τ+).
    HOSTILE requires only one party to be hostile (either < τ-).
    Otherwise NEUTRAL.
    """
    disp_a_to_b = social_a.get_disposition(agent_b_id)
    disp_b_to_a = social_b.get_disposition(agent_a_id)

    # HOSTILE is unilateral — if either dislikes the other enough
    if disp_a_to_b < hostile_threshold or disp_b_to_a < hostile_threshold:
        return AllianceStatus.HOSTILE

    # ALLIED requires mutual consent
    if disp_a_to_b > allied_threshold and disp_b_to_a > allied_threshold:
        return AllianceStatus.ALLIED

    return AllianceStatus.NEUTRAL


def get_alliance_status_for_agent(
    agent_id: str,
    other_id: str,
    social_models: dict[str, SocialModel],
    allied_threshold: float = 0.5,
    hostile_threshold: float = -0.3,
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
        hostile_threshold,
    )
