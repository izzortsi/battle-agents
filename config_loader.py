"""Configuration loader — reads YAML config and character files."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from agent.agent import Agent
from agent.attributes import Attributes, BalanceConfig, set_balance
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


def load_balance_config(game_cfg: dict[str, Any] | None = None) -> BalanceConfig:
    """Build a BalanceConfig from the 'balance' section of game_config.yaml.

    Also calls set_balance() so that Attributes derived properties use it.
    """
    if game_cfg is None:
        game_cfg = load_game_config()
    raw = game_cfg.get("balance", {})
    cfg = BalanceConfig(
        **{k: v for k, v in raw.items() if k in BalanceConfig.__dataclass_fields__}
    )
    set_balance(cfg)
    return cfg


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
    abilities_data = data.get("abilities", [])
    attributes = Attributes(
        atk=attrs_data.get("atk", 10),
        mgk=attrs_data.get("mgk", 10),
        spd=attrs_data.get("spd", 10),
        con=attrs_data.get("con", 10),
        hit=attrs_data.get("hit", 10),
        attack_range=attrs_data.get("attack_range", 1),
        abilities=abilities_data if abilities_data else [],
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
