"""Two-layer character generation prompts.

Layer 1 (Narrative): name + description → combat_class, backstory, personality_traits
Layer 2 (Mechanics): Layer 1 output → stats, abilities with full effect schema

The LLM is taught about all 9 behaviors, 5 AoE patterns, and the full effect
schema so it can generate mechanically valid characters.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Layer 1 — Narrative identity
# ---------------------------------------------------------------------------

LAYER1_SYSTEM = """\
You are a character designer for a tactical combat arena game.
Given a character's name and a brief description, generate their narrative \
identity: combat class, backstory, and personality traits.

The combat class should be a single word or short phrase (e.g., "warrior", \
"shadow mage", "battle cleric", "gunslinger", "berserker").

The backstory should be 2-4 sentences establishing who they are, their \
motivation, and their history. Make it vivid and specific.

Personality traits should be 3-5 adjectives or short phrases that capture \
how they behave in and out of combat.

Respond with a JSON object only. No other text. Schema:
{
  "combat_class": "<class string>",
  "backstory": "<2-4 sentence backstory>",
  "personality_traits": ["<trait1>", "<trait2>", "<trait3>"]
}"""


def build_layer1_user(name: str, description: str) -> str:
    """Build the Layer 1 user prompt."""
    return (
        f"Character name: {name}\n"
        f"Description: {description}\n\n"
        f"Generate this character's narrative identity."
    )


# ---------------------------------------------------------------------------
# Layer 2 — Mechanical stats and abilities
# ---------------------------------------------------------------------------

LAYER2_SYSTEM = """\
You are a combat mechanics designer for a tactical arena game.
Given a character's narrative identity (name, class, backstory, personality), \
generate their combat stats and exactly 2 abilities.

STATS (each an integer 1-20):
  - atk: Physical damage power
  - mgk: Magical damage power and mana pool size
  - spd: Initiative, evasion, movement bonus (15+ can trigger bonus actions)
  - con: HP pool, contributes to both defences
  - hit: Accuracy, counter-attack chance
  - attack_range: 1 for melee, 2-3 for ranged (integer)

Stats should reflect the character's class and fighting style. A warrior \
should have high ATK/CON, a mage high MGK, a rogue high SPD/HIT, etc.

ABILITIES — generate exactly 2. Each ability has:
  - name: Thematic ability name
  - mana_cost: Integer 3-10
  - damage: Integer 0-25 (0 for pure utility/heal abilities)
  - range: Integer 1-4 (Manhattan distance)
  - aoe_pattern: One of "single", "line", "cross", "radius", "cone"
    - single: hits 1 tile
    - line: hits 3 tiles along dominant axis from caster to target
    - cross: hits + shape (5 tiles) centered on target
    - radius: hits 3x3 area (9 tiles) centered on target
    - cone: fan shape widening from caster toward target
  - cooldown: Integer 2-5 (turns before reuse)
  - current_cd: Always 0 (starts off cooldown)
  - description: 1-2 sentences describing what it does narratively
  - tactical_hint: 1 sentence on when/why to use it
  - effects: List of effect dicts (can be empty for pure-damage abilities)

EFFECT SCHEMA — each effect in the effects list:
  - type: A thematic name (e.g., "burn", "stun", "enrage", "poison", \
"frostbite", "blind"). Can be novel — the registry will classify it.
  - behavior: One of these 9 mechanical categories:
    * "miss_chance" — attacks/abilities may miss (magnitude = miss probability)
    * "skip_turn" — target loses their entire turn
    * "prevent_move" — target cannot move
    * "damage_over_time" — deals magnitude * max_hp damage per round
    * "reduce_outgoing_damage" — reduces target's outgoing damage by magnitude
    * "boost_outgoing_damage" — boosts caster's outgoing damage by magnitude
    * "reduce_incoming_damage" — reduces incoming damage by magnitude
    * "stat_modifier" — boosts speed/movement
    * "passive" — tracked but no automatic enforcement
  - duration: Integer 1-3 turns
  - magnitude: Float 0.0-0.5 (meaning depends on behavior)
  - target: "self" for buffs/heals on caster, "enemy" for debuffs on target
  - category: "buff", "debuff", "heal", or "movement"
    * "heal" with target "self" restores magnitude * max_hp as HP
    * "buff" applies a status to the caster
    * "debuff" applies a status to the target (rolled against chance)
    * "movement" teleports caster to an adjacent tile near target
  - chance: Float 0.0-1.0 (probability of application; 1.0 for buffs, \
0.6-0.85 for debuffs)

DESIGN GUIDELINES:
- One ability should be the character's signature offensive/utility move
- The second should complement their kit (CC, buff, heal, AoE, etc.)
- Effects should be thematically consistent with the character
- A healer class should have at least one heal effect (category: "heal", \
target: "self", behavior can be "passive")
- Pure-damage abilities (no effects) are fine for straightforward fighters
- Self-targeting abilities (all effects target "self") need damage: 0

Respond with a JSON object only. No other text. Schema:
{
  "attributes": {
    "atk": <int>,
    "mgk": <int>,
    "spd": <int>,
    "con": <int>,
    "hit": <int>,
    "attack_range": <int>
  },
  "abilities": [
    {
      "name": "<string>",
      "mana_cost": <int>,
      "damage": <int>,
      "range": <int>,
      "aoe_pattern": "<string>",
      "cooldown": <int>,
      "current_cd": 0,
      "description": "<string>",
      "tactical_hint": "<string>",
      "effects": [
        {
          "type": "<string>",
          "behavior": "<string>",
          "duration": <int>,
          "magnitude": <float>,
          "target": "<self|enemy>",
          "category": "<buff|debuff|heal|movement>",
          "chance": <float>
        }
      ]
    }
  ]
}"""


def build_layer2_user(
    name: str,
    description: str,
    combat_class: str,
    backstory: str,
    personality_traits: list[str],
) -> str:
    """Build the Layer 2 user prompt with Layer 1 output."""
    traits_str = ", ".join(personality_traits)
    return (
        f"Character name: {name}\n"
        f"Original description: {description}\n"
        f"Combat class: {combat_class}\n"
        f"Backstory: {backstory}\n"
        f"Personality: {traits_str}\n\n"
        f"Generate combat stats and exactly 2 abilities for this character."
    )
