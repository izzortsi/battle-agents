"""Agent class — ties together identity, attributes, knowledge, and social model."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.attributes import Attributes
from agent.identity import Identity
from agent.social_model import SocialModel
from ontology.knowledge import AgentKnowledge


@dataclass
class Agent:
    """A single agent in the simulation."""

    agent_id: str
    identity: Identity
    attributes: Attributes = field(default_factory=Attributes)
    knowledge: AgentKnowledge = field(default_factory=AgentKnowledge)
    social: SocialModel = field(init=False)

    def __post_init__(self) -> None:
        self.social = SocialModel(self.agent_id)

    @property
    def is_alive(self) -> bool:
        return self.attributes.is_alive

    @property
    def name(self) -> str:
        return self.identity.name

    def status_summary(self) -> str:
        a = self.attributes
        status_str = ""
        if a.status_effects:
            effects = [e["type"] for e in a.status_effects]
            status_str = f" [{', '.join(effects)}]"
        return (
            f"{self.identity.name} ({self.identity.combat_class}) "
            f"HP:{a.hp}/{a.max_hp} MP:{a.mana}/{a.max_mana} "
            f"ATK:{a.atk} MGK:{a.mgk} SPD:{a.spd} CON:{a.con} HIT:{a.hit}"
            f"{status_str}"
        )

    def __str__(self) -> str:
        return self.status_summary()

    def __hash__(self) -> int:
        return hash(self.agent_id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Agent):
            return NotImplemented
        return self.agent_id == other.agent_id
