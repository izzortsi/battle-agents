"""Planning prompt templates — builds LLM prompts for plan generation.

Used by cognition/planner.py to generate high-level and immediate plans.
Plans are stored as MemoryNodes and participate in retrieval.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cognition.memory_stream import MemoryNode


# -- High-level plan generation ----------------------------------------------

_DEFAULT_LOCATION_CONTEXT = (
    "You are in a dangerous combat arena. "
    "Survival requires both martial skill and social cunning. "
    "Alliances can form and break. Trust is earned, betrayal is punished."
)

_DEFAULT_PLAN_DIRECTIVES = """\
Generate a high-level plan based on your current situation, \
memories, relationships, and personality. The plan MUST address:
- WHO are your primary threats and why
- WHO might be a potential ally (based on disposition and past interactions)
- HOW you will approach them (socially or aggressively)
- WHEN you will use defensive or social tactics

Your plan should be action-oriented and reflect the current phase. \
Smart fighters choose their enemies carefully and leverage alliances. \
Pure passivity will get you killed."""

_DEFAULT_CLOSING_INSTRUCTION = (
    "Generate your battle plan. Focus on threats, alliances, and survival."
)

_DEFAULT_STAT_BLOCK = """\
  HP: {hp}/{max_hp}  |  Mana: {mana}/{max_mana}
  ATK: {atk}  |  MGK: {mgk}  |  SPD: {spd}  |  CON: {con}  |  HIT: {hit}
  Damage type: {damage_type}  |  Attack range: {attack_range}"""

PLAN_SYSTEM = """\
You are {name}, a {combat_class}. {location_context}

PERSONALITY: {personality}
BACKSTORY: {backstory}

{plan_directives}

Respond with a JSON object:
{{
  "plan": "<your plan, 2-4 sentences, in character>",
  "priorities": ["<priority 1>", "<priority 2>", "<priority 3>"]
}}

Your plan should reflect your personality, relationships, and the current situation.\
"""


PLAN_USER = """\
CURRENT SITUATION:
  Round: {round_number}
  Position: ({my_x}, {my_y})
{stat_block}

RELATIONSHIPS:
{relationships}

RELEVANT MEMORIES:
{memories}

{trigger_context}

{closing_instruction} \
JSON only.\
"""


# -- Immediate plan (per-turn) -----------------------------------------------

IMMEDIATE_PLAN_SYSTEM = """\
You are {name}, a {combat_class}. Given your high-level plan and current \
situation, determine your immediate tactical intention for THIS turn.

Respond with a JSON object:
{{
  "immediate_plan": "<1 sentence describing what you intend to do this turn and why>"
}}\
"""

IMMEDIATE_PLAN_USER = """\
YOUR HIGH-LEVEL PLAN: {high_level_plan}

CURRENT SITUATION:
  Round: {round_number}
  Position: ({my_x}, {my_y})
  HP: {hp}/{max_hp}

VISIBLE ENEMIES:
{enemies}

What is your immediate intention for THIS turn?
JSON only.\
"""


# -- Builder functions -------------------------------------------------------


def build_plan_prompts(
    agent_name: str,
    combat_class: str,
    personality: str,
    backstory: str,
    round_number: int,
    my_x: int,
    my_y: int,
    hp: int,
    max_hp: int,
    mana: int,
    max_mana: int,
    atk: int,
    mgk: int,
    spd: int,
    con: int,
    hit: int,
    damage_type: str,
    attack_range: int,
    relationships_text: str,
    memories: list[MemoryNode],
    trigger_context: str = "",
    location_context: str = "",
    plan_directives: str = "",
    closing_instruction: str = "",
    show_combat_stats: bool = True,
) -> tuple[str, str]:
    """Build system + user prompts for high-level plan generation."""
    system = PLAN_SYSTEM.format(
        name=agent_name,
        combat_class=combat_class,
        personality=personality,
        backstory=backstory,
        location_context=location_context or _DEFAULT_LOCATION_CONTEXT,
        plan_directives=plan_directives or _DEFAULT_PLAN_DIRECTIVES,
    )

    mem_text = _format_plan_memories(memories)

    if show_combat_stats:
        stat_block = _DEFAULT_STAT_BLOCK.format(
            hp=hp,
            max_hp=max_hp,
            mana=mana,
            max_mana=max_mana,
            atk=atk,
            mgk=mgk,
            spd=spd,
            con=con,
            hit=hit,
            damage_type=damage_type,
            attack_range=attack_range,
        )
    else:
        stat_block = ""

    user = PLAN_USER.format(
        round_number=round_number,
        my_x=my_x,
        my_y=my_y,
        stat_block=stat_block,
        relationships=relationships_text,
        memories=mem_text,
        trigger_context=trigger_context or "Battle is underway.",
        closing_instruction=closing_instruction or _DEFAULT_CLOSING_INSTRUCTION,
    )

    return system, user


def build_immediate_plan_prompts(
    agent_name: str,
    combat_class: str,
    high_level_plan: str,
    round_number: int,
    my_x: int,
    my_y: int,
    hp: int,
    max_hp: int,
    enemies_text: str,
) -> tuple[str, str]:
    """Build system + user prompts for immediate (per-turn) plan."""
    system = IMMEDIATE_PLAN_SYSTEM.format(
        name=agent_name,
        combat_class=combat_class,
    )
    user = IMMEDIATE_PLAN_USER.format(
        high_level_plan=high_level_plan,
        round_number=round_number,
        my_x=my_x,
        my_y=my_y,
        hp=hp,
        max_hp=max_hp,
        enemies=enemies_text,
    )
    return system, user


def _format_plan_memories(memories: list[MemoryNode]) -> str:
    """Format memories for the planning prompt."""
    if not memories:
        return "  (no relevant memories)"
    lines = []
    for i, m in enumerate(memories, 1):
        tag = f"[{m.memory_type.value}]" if m.memory_type.value != "observation" else ""
        lines.append(f"  {i}. [turn {m.turn_created}] {tag} {m.description}")
    return "\n".join(lines)


def format_relationships_for_plan(
    relationships: dict[str, tuple[float, str]],
) -> str:
    """Format relationship summaries for the planning prompt.

    relationships: dict mapping agent_name -> (disposition, status_label)
    """
    if not relationships:
        return "  (no known relationships)"
    lines = []
    for name, (disp, label) in relationships.items():
        lines.append(f"  - {name}: {disp:+.2f} ({label})")
    return "\n".join(lines)
