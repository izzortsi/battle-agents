"""Configuration loader — reads YAML config and character files."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from agent.agent import Agent
from agent.attributes import Attributes
from agent.identity import Identity

CONFIG_DIR = Path(__file__).parent / "config"


def load_yaml(path: str | Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_game_config(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else CONFIG_DIR / "game_config.yaml"
    return load_yaml(p)


def load_llm_config(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else CONFIG_DIR / "llm_config.yaml"
    return load_yaml(p)


def load_character(path: str | Path) -> Agent:
    """Load a single character YAML into an Agent."""
    data = load_yaml(path)
    identity = Identity(
        name=data["name"],
        backstory=data.get("backstory", ""),
        personality_traits=data.get("personality_traits", []),
        combat_class=data.get("combat_class", "warrior"),
    )
    attrs_data = data.get("attributes", {})
    attributes = Attributes(
        max_hp=attrs_data.get("max_hp", 100),
        hp=attrs_data.get("hp", attrs_data.get("max_hp", 100)),
        max_mana=attrs_data.get("max_mana", 50),
        mana=attrs_data.get("mana", attrs_data.get("max_mana", 50)),
        attack=attrs_data.get("attack", 15),
        defense=attrs_data.get("defense", 5),
        speed=attrs_data.get("speed", 10),
        move_range=attrs_data.get("move_range", 3),
        attack_range=attrs_data.get("attack_range", 1),
    )
    agent_id = data["name"].lower().replace(" ", "_")
    return Agent(agent_id=agent_id, identity=identity, attributes=attributes)


def load_all_characters(directory: str | Path | None = None) -> list[Agent]:
    """Load all character YAMLs from a directory."""
    d = Path(directory) if directory else CONFIG_DIR / "characters"
    agents = []
    for p in sorted(d.glob("*.yaml")):
        agents.append(load_character(p))
    return agents
