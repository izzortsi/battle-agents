"""Character generator — two-layer LLM pipeline.

Layer 1 (Narrative): name + description → combat_class, backstory, personality_traits
Layer 2 (Mechanics): Layer 1 output → attributes, abilities

Public API:
    generate_character(name, description, llm) -> dict
    to_yaml(data) -> str
    save_character(data, directory) -> Path
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from combat.status_registry import ensure_registered, get_behavior
from llm.adapter import LLMAdapter
from llm.json_utils import extract_json
from llm.prompts.character_gen import (
    LAYER1_SYSTEM,
    LAYER2_SYSTEM,
    build_layer1_user,
    build_layer2_user,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_AOE_PATTERNS = {"single", "line", "cross", "radius", "cone"}

_STAT_KEYS = ("atk", "mgk", "spd", "con", "hit")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_character(name: str, description: str, llm: LLMAdapter) -> dict:
    """Generate a complete character dict from *name* and *description*.

    Uses two sequential LLM calls:
      1. Narrative identity (class, backstory, personality)
      2. Mechanical stats and abilities

    Returns a dict matching the character YAML schema, validated and fixed.
    """
    # --- Layer 1: Narrative ---
    log.info("Layer 1: Generating narrative identity for '%s'...", name)
    layer1_raw = llm.complete(
        system=LAYER1_SYSTEM,
        user=build_layer1_user(name, description),
        max_tokens=512,
        temperature=0.8,
        response_format="json",
    )
    layer1 = extract_json(layer1_raw)
    log.info(
        "  combat_class=%s  traits=%s",
        layer1.get("combat_class", "?"),
        layer1.get("personality_traits", []),
    )

    combat_class: str = layer1.get("combat_class", "fighter")
    backstory: str = layer1.get("backstory", f"{name} is a mysterious combatant.")
    personality_traits: list[str] = layer1.get(
        "personality_traits", ["determined", "resourceful", "bold"]
    )

    # --- Layer 2: Mechanics ---
    log.info("Layer 2: Generating stats and abilities for '%s'...", name)
    layer2_raw = llm.complete(
        system=LAYER2_SYSTEM,
        user=build_layer2_user(
            name, description, combat_class, backstory, personality_traits
        ),
        max_tokens=1024,
        temperature=0.7,
        response_format="json",
    )
    layer2 = extract_json(layer2_raw)

    # --- Merge into final character dict ---
    data: dict = {
        "name": name,
        "combat_class": combat_class,
        "backstory": backstory,
        "personality_traits": personality_traits,
        "attributes": layer2.get("attributes", {}),
        "abilities": layer2.get("abilities", []),
    }

    data = _validate_and_fix(data)
    log.info("Character '%s' generated and validated.", name)
    return data


def to_yaml(data: dict) -> str:
    """Serialize a character dict to YAML string."""
    # Order keys to match existing character files.
    ordered: dict = {}
    for key in (
        "name",
        "combat_class",
        "backstory",
        "personality_traits",
        "attributes",
        "abilities",
    ):
        if key in data:
            ordered[key] = data[key]
    # Include any extra keys that may exist.
    for key in data:
        if key not in ordered:
            ordered[key] = data[key]

    return yaml.dump(
        ordered, default_flow_style=False, sort_keys=False, allow_unicode=True, width=80
    )


def save_character(data: dict, directory: str | Path = "config/characters") -> Path:
    """Write the character to a YAML file and return the Path."""
    dir_path = Path(directory)
    dir_path.mkdir(parents=True, exist_ok=True)

    filename = data.get("name", "unknown").lower().replace(" ", "_") + ".yaml"
    filepath = dir_path / filename

    filepath.write_text(to_yaml(data), encoding="utf-8")
    log.info("Saved character to %s", filepath)
    return filepath


# ---------------------------------------------------------------------------
# Validation / fix-up
# ---------------------------------------------------------------------------


def _clamp(value: int | float, lo: int | float, hi: int | float) -> int | float:
    """Clamp *value* between *lo* and *hi*."""
    return max(lo, min(hi, value))


def _validate_and_fix(data: dict) -> dict:
    """Ensure the character dict has all required fields with sane values.

    Fills missing defaults, clamps stats, validates AoE patterns, registers
    novel status types with the status registry.
    """
    # --- Attributes ---
    attrs = data.setdefault("attributes", {})
    for stat in _STAT_KEYS:
        val = attrs.get(stat)
        if val is None:
            attrs[stat] = 10
        else:
            attrs[stat] = int(_clamp(int(val), 1, 20))

    ar = attrs.get("attack_range")
    if ar is None:
        attrs["attack_range"] = 1
    else:
        attrs["attack_range"] = int(_clamp(int(ar), 1, 4))

    # --- Abilities ---
    abilities: list[dict] = data.get("abilities", [])

    # Ensure exactly 2 abilities — pad with placeholder if needed.
    while len(abilities) < 2:
        idx = len(abilities) + 1
        abilities.append(
            {
                "name": f"Ability {idx}",
                "mana_cost": 5,
                "damage": 10,
                "range": 1,
                "aoe_pattern": "single",
                "cooldown": 3,
                "current_cd": 0,
                "description": f"A basic combat ability.",
                "tactical_hint": "Use when in range of an enemy.",
                "effects": [],
            }
        )

    # Trim to 2 if the LLM over-generated.
    abilities = abilities[:2]

    for ability in abilities:
        _fix_ability(ability)

    data["abilities"] = abilities
    return data


def _fix_ability(ability: dict) -> None:
    """Fill defaults and validate a single ability dict in-place."""
    ability.setdefault("name", "Unnamed Ability")
    ability.setdefault("mana_cost", 5)
    ability.setdefault("damage", 0)
    ability.setdefault("range", 1)
    ability.setdefault("aoe_pattern", "single")
    ability.setdefault("cooldown", 3)
    ability["current_cd"] = 0  # always starts off cooldown
    ability.setdefault("description", "A combat ability.")
    ability.setdefault("tactical_hint", "Use when appropriate.")

    # Validate AoE pattern.
    if ability["aoe_pattern"] not in _VALID_AOE_PATTERNS:
        log.warning(
            "Invalid aoe_pattern '%s' on ability '%s'; defaulting to 'single'.",
            ability["aoe_pattern"],
            ability.get("name"),
        )
        ability["aoe_pattern"] = "single"

    # Clamp numeric fields.
    ability["mana_cost"] = int(_clamp(int(ability["mana_cost"]), 1, 20))
    ability["damage"] = int(_clamp(int(ability["damage"]), 0, 50))
    ability["range"] = int(_clamp(int(ability["range"]), 1, 6))
    ability["cooldown"] = int(_clamp(int(ability["cooldown"]), 1, 10))

    # --- Effects ---
    effects: list[dict] = ability.get("effects", [])
    for effect in effects:
        _fix_effect(effect)
    ability["effects"] = effects


def _fix_effect(effect: dict) -> None:
    """Fill defaults and validate a single effect dict in-place."""
    effect.setdefault("type", "unknown")
    effect.setdefault("duration", 1)
    effect.setdefault("magnitude", 0.0)
    effect.setdefault("target", "enemy")
    effect.setdefault("category", "debuff")
    effect.setdefault("chance", 0.7)

    # Infer behavior from type if missing or invalid.
    behavior = effect.get("behavior", "")
    if not behavior or behavior not in {
        "miss_chance",
        "skip_turn",
        "prevent_move",
        "damage_over_time",
        "reduce_outgoing_damage",
        "boost_outgoing_damage",
        "reduce_incoming_damage",
        "stat_modifier",
        "passive",
    }:
        effect["behavior"] = get_behavior(effect["type"])

    # Clamp numeric fields.
    effect["duration"] = int(_clamp(int(effect["duration"]), 1, 10))
    effect["magnitude"] = float(_clamp(float(effect["magnitude"]), 0.0, 1.0))
    effect["chance"] = float(_clamp(float(effect["chance"]), 0.0, 1.0))

    # Ensure target is valid.
    if effect["target"] not in ("self", "enemy"):
        effect["target"] = "enemy"

    # Ensure category is valid.
    if effect["category"] not in ("buff", "debuff", "heal", "movement"):
        effect["category"] = "debuff"

    # Register novel types with the status registry.
    ensure_registered(effect)
