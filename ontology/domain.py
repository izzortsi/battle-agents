"""Entity base classes for the ontological domain.

Domain D = {Agent, Location, Object, Event, Action}
Every entity has a unique id and a type tag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EntityType(str, Enum):
    AGENT = "agent"
    LOCATION = "location"
    OBJECT = "object"
    EVENT = "event"
    ACTION = "action"


@dataclass(frozen=True)
class Entity:
    """Base for all domain entities.  Frozen so it can be used in sets/dicts."""

    entity_id: str
    entity_type: EntityType

    def __str__(self) -> str:
        return self.entity_id


@dataclass(frozen=True)
class AgentEntity(Entity):
    entity_type: EntityType = field(default=EntityType.AGENT, init=False)


@dataclass(frozen=True)
class LocationEntity(Entity):
    entity_type: EntityType = field(default=EntityType.LOCATION, init=False)


@dataclass(frozen=True)
class ObjectEntity(Entity):
    entity_type: EntityType = field(default=EntityType.OBJECT, init=False)


@dataclass(frozen=True)
class EventEntity(Entity):
    entity_type: EntityType = field(default=EntityType.EVENT, init=False)


@dataclass(frozen=True)
class ActionEntity(Entity):
    entity_type: EntityType = field(default=EntityType.ACTION, init=False)
