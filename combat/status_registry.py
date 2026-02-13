"""Status registry — maps arbitrary status type names to mechanical behaviors.

Nine behaviors exist; unlimited type names can map to them.  Novel types
from LLM-generated characters are registered at load time via ensure_registered().

Lookup chain (get_behavior):
  1. Exact match in _KNOWN
  2. Keyword inference (_infer_behavior)
  3. Fallback to "passive"
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Valid behaviors — the only nine mechanical categories the resolver enforces.
# ---------------------------------------------------------------------------
VALID_BEHAVIORS: set[str] = {
    "miss_chance",  # attacks/abilities may miss (magnitude = miss prob)
    "skip_turn",  # lose entire turn
    "prevent_move",  # cannot move
    "damage_over_time",  # takes magnitude * max_hp damage per round
    "reduce_outgoing_damage",  # outgoing damage * (1 - magnitude)
    "boost_outgoing_damage",  # outgoing damage * (1 + magnitude)
    "reduce_incoming_damage",  # incoming damage * (1 - magnitude)
    "stat_modifier",  # boosts initiative speed; +1 movement range
    "passive",  # tracked/displayed but no auto enforcement
}

# ---------------------------------------------------------------------------
# Known type -> behavior mapping.  Populated with base types + common synonyms.
# ---------------------------------------------------------------------------
_KNOWN: dict[str, str] = {
    # --- Base types ---
    "blind": "miss_chance",
    "stun": "skip_turn",
    "poison": "damage_over_time",
    "slow": "prevent_move",
    "defend": "reduce_incoming_damage",
    "weaken": "reduce_outgoing_damage",
    "empower": "boost_outgoing_damage",
    "haste": "stat_modifier",
    "shield": "reduce_incoming_damage",
    # --- Common synonyms ---
    "burn": "damage_over_time",
    "bleed": "damage_over_time",
    "freeze": "prevent_move",
    "paralyze": "skip_turn",
    "paralysis": "skip_turn",
    "root": "prevent_move",
    "entangle": "prevent_move",
    "immobilize": "prevent_move",
    "silence": "passive",
    "curse": "reduce_outgoing_damage",
    "bless": "boost_outgoing_damage",
    "barrier": "reduce_incoming_damage",
    "enrage": "boost_outgoing_damage",
    "cripple": "reduce_outgoing_damage",
    "daze": "miss_chance",
    "confuse": "miss_chance",
    "fear": "skip_turn",
    "terrify": "skip_turn",
    "regen": "passive",
    "regenerate": "passive",
    "fortify": "reduce_incoming_damage",
    "bolster": "boost_outgoing_damage",
    "enfeeble": "reduce_outgoing_damage",
    "corrode": "reduce_incoming_damage",  # reduces target armor -> incoming dmg up; but we map to passive-safe
    "venom": "damage_over_time",
    "ignite": "damage_over_time",
    "frostbite": "damage_over_time",
    "hemorrhage": "damage_over_time",
    "petrify": "skip_turn",
    "snare": "prevent_move",
}

# ---------------------------------------------------------------------------
# Keyword -> behavior mapping for inference of unknown types.
# Each entry: (keyword_list, behavior).  Checked in order; first match wins.
# ---------------------------------------------------------------------------
_KEYWORD_MAP: list[tuple[list[str], str]] = [
    # damage over time — checked first because many overlap with other categories
    (
        [
            "burn",
            "fire",
            "immolat",
            "ignit",
            "scorch",
            "sear",
            "poison",
            "venom",
            "toxic",
            "blight",
            "bleed",
            "hemorrhag",
            "lacerat",
            "corrod",
            "acid",
            "decay",
            "rot",
            "wither",
            "frostbit",
        ],
        "damage_over_time",
    ),
    # skip turn
    (
        [
            "stun",
            "paralyz",
            "paralys",
            "petri",
            "petrif",
            "fear",
            "terrif",
            "horrif",
            "incapacit",
            "knockout",
            "sleep",
            "unconscious",
        ],
        "skip_turn",
    ),
    # prevent move
    (
        [
            "root",
            "entangl",
            "immobi",
            "snare",
            "anchor",
            "pin",
            "freeze",
            "frozen",
            "ice",
            "slow",
            "hobbl",
            "crippl",
            "grappl",
            "bind",
            "trap",
            "web",
        ],
        "prevent_move",
    ),
    # miss chance
    (
        [
            "blind",
            "daze",
            "dazzl",
            "confus",
            "disorient",
            "obscur",
            "fog",
            "haze",
            "smoke",
            "sand",
        ],
        "miss_chance",
    ),
    # reduce outgoing damage
    (
        [
            "weaken",
            "enfeebl",
            "exhaust",
            "fatigue",
            "sap",
            "curse",
            "hex",
            "debilitat",
            "frail",
        ],
        "reduce_outgoing_damage",
    ),
    # boost outgoing damage
    (
        [
            "empower",
            "enrage",
            "bolster",
            "amplif",
            "bless",
            "might",
            "fury",
            "feroc",
            "strengthen",
        ],
        "boost_outgoing_damage",
    ),
    # reduce incoming damage
    (
        [
            "shield",
            "barrier",
            "ward",
            "protect",
            "fortif",
            "armor",
            "aegis",
            "bulwark",
            "guard",
            "defend",
        ],
        "reduce_incoming_damage",
    ),
    # stat modifier
    (
        ["haste", "swift", "quicken", "accelerat", "speed", "agil", "nimbl"],
        "stat_modifier",
    ),
]


def get_behavior(type_name: str) -> str:
    """Return the mechanical behavior for *type_name*.

    Lookup chain: exact → keyword inference → "passive".
    """
    low = type_name.lower().strip()
    if low in _KNOWN:
        return _KNOWN[low]
    inferred = _infer_behavior(low)
    if inferred is not None:
        return inferred
    return "passive"


def _infer_behavior(type_name: str) -> str | None:
    """Attempt to infer behavior from keywords in *type_name*."""
    normalized = type_name.lower().replace("_", " ").replace("-", " ")
    for keywords, behavior in _KEYWORD_MAP:
        for kw in keywords:
            if kw in normalized:
                return behavior
    return None


def ensure_registered(effect: dict) -> None:
    """Ensure a status type is in the registry.

    If the effect dict has a valid ``behavior`` field, use that.
    Otherwise infer from the type name.  Either way, persist so future
    lookups are O(1).
    """
    type_name = effect.get("type", "").lower().strip()
    if not type_name:
        return
    if type_name in _KNOWN:
        return  # already registered

    # Trust the effect's own behavior field if valid.
    explicit = effect.get("behavior", "").lower().strip()
    if explicit in VALID_BEHAVIORS:
        _KNOWN[type_name] = explicit
        return

    # Infer from name.
    inferred = _infer_behavior(type_name)
    _KNOWN[type_name] = inferred if inferred else "passive"


def is_registered(type_name: str) -> bool:
    return type_name.lower().strip() in _KNOWN


def all_registered() -> dict[str, str]:
    """Return a copy of the current registry (for debugging / display)."""
    return dict(_KNOWN)
