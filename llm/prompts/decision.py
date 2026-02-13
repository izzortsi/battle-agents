"""Decision prompt template — builds the LLM prompt for combat action selection.

The prompt gives the agent its identity, current state, perceptions,
retrieved memories, and the available action space, then asks for a JSON
action response.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.agent import Agent
    from cognition.memory_stream import MemoryNode


# -- System prompt (character sheet + rules) --------------------------------

SYSTEM_TEMPLATE = """\
You are {name}, a {combat_class} in a tactical combat arena.

PERSONALITY: {personality}
BACKSTORY: {backstory}

You must stay in character at all times. Your decisions should reflect your \
personality traits, your memories, and your tactical assessment of the situation.

RULES:
- You are on a 2D tile grid. Coordinates are (x, y).
- Each turn you must choose exactly ONE action.
- You can only attack targets within your attack range ({attack_range} tiles, Manhattan distance).
- You can move to an adjacent tile (up/down/left/right) if it is passable and unoccupied.
- DEFEND raises your defense for one turn (diminishing returns if used consecutively).
- WAIT does nothing.
- CHAT sends a message to another agent (costs your action).

Respond with a JSON object. No other text. The JSON must have this exact schema:
{{
  "reasoning": "<your internal tactical reasoning, 1-3 sentences, in character>",
  "action": "<one of: move, attack, defend, wait, chat>",
  "target_tile": "<x_y format, required for move, omit otherwise>",
  "target_agent": "<agent_id, required for attack/chat, omit otherwise>",
  "message": "<message text, required for chat, omit otherwise>"
}}
"""


# -- User prompt (situation + perceptions + memories) -----------------------

USER_TEMPLATE = """\
ROUND {round_number}, YOUR TURN.

YOUR STATUS:
  Position: ({my_x}, {my_y})
  HP: {hp}/{max_hp}  |  Mana: {mana}/{max_mana}
  Attack: {attack}  |  Defense: {defense}  |  Speed: {speed}
  Move range: {move_range}  |  Attack range: {attack_range}
{status_effects_line}
{plan_section}
CURRENT PERCEPTIONS:
{perceptions}

RELEVANT MEMORIES:
{memories}

ENEMIES YOU CAN SEE:
{visible_enemies}

AVAILABLE ACTIONS:
{available_actions}

Choose your action. Respond with JSON only."""


# -- Builder functions ------------------------------------------------------


def build_system_prompt(agent: Agent) -> str:
    """Build the system prompt from an agent's identity and attributes."""
    personality = ", ".join(agent.identity.personality_traits) or "unknown"
    return SYSTEM_TEMPLATE.format(
        name=agent.identity.name,
        combat_class=agent.identity.combat_class,
        personality=personality,
        backstory=agent.identity.backstory,
        attack_range=agent.attributes.attack_range,
    )


def format_memories(memories: list[MemoryNode]) -> str:
    """Format retrieved memories for the prompt."""
    if not memories:
        return "  (no relevant memories)"
    lines = []
    for i, m in enumerate(memories, 1):
        turn_label = f"[turn {m.turn_created}]"
        lines.append(f"  {i}. {turn_label} {m.description}")
    return "\n".join(lines)


def format_visible_enemies(
    enemies: list[dict],
    social_dispositions: dict[str, float] | None = None,
) -> str:
    """Format visible enemy information.

    Each dict: {name, agent_id, x, y, distance, hp, max_hp}
    social_dispositions: optional map of agent_id -> disposition float.
    """
    if not enemies:
        return "  (none visible)"
    lines = []
    for e in enemies:
        hp_pct = int(100 * e["hp"] / e["max_hp"]) if e["max_hp"] > 0 else 0
        in_range = "IN RANGE" if e.get("in_attack_range") else ""
        disp_str = ""
        if social_dispositions and e["agent_id"] in social_dispositions:
            d = social_dispositions[e["agent_id"]]
            if d > 0.5:
                label = "allied"
            elif d > 0.15:
                label = "friendly"
            elif d < -0.3:
                label = "hostile"
            elif d < -0.1:
                label = "unfriendly"
            else:
                label = "neutral"
            disp_str = f" [disposition: {d:+.2f} ({label})]"
        lines.append(
            f"  - {e['name']} ({e['agent_id']}) at ({e['x']}, {e['y']}), "
            f"distance {e['distance']}, HP {e['hp']}/{e['max_hp']} ({hp_pct}%) {in_range}{disp_str}"
        )
    return "\n".join(lines)


def format_available_actions(
    can_move: list[str],
    can_attack: list[str],
    can_chat: list[str],
) -> str:
    """Format the set of available actions for the prompt."""
    lines = []
    if can_attack:
        lines.append(f"  ATTACK targets: {', '.join(can_attack)}")
    if can_move:
        # Show up to 6 move options to avoid prompt bloat
        display = can_move[:6]
        extra = f" (+{len(can_move) - 6} more)" if len(can_move) > 6 else ""
        lines.append(f"  MOVE to tiles: {', '.join(display)}{extra}")
    lines.append("  DEFEND (raise defense this turn)")
    lines.append("  WAIT (do nothing)")
    if can_chat:
        lines.append(f"  CHAT with: {', '.join(can_chat)}")
    return "\n".join(lines)


def build_user_prompt(
    agent: Agent,
    round_number: int,
    my_x: int,
    my_y: int,
    perceptions_text: str,
    memories: list[MemoryNode],
    visible_enemies: list[dict],
    can_move: list[str],
    can_attack: list[str],
    can_chat: list[str],
    current_plan: str = "",
    social_dispositions: dict[str, float] | None = None,
) -> str:
    """Build the user prompt with full situational context."""
    status_effects = agent.attributes.status_effects
    if status_effects:
        effects_str = ", ".join(e["type"] for e in status_effects)
        status_effects_line = f"  Active effects: {effects_str}"
    else:
        status_effects_line = ""

    if current_plan:
        plan_section = f"\nYOUR CURRENT PLAN:\n  {current_plan}\n"
    else:
        plan_section = ""

    return USER_TEMPLATE.format(
        round_number=round_number,
        my_x=my_x,
        my_y=my_y,
        hp=agent.attributes.hp,
        max_hp=agent.attributes.max_hp,
        mana=agent.attributes.mana,
        max_mana=agent.attributes.max_mana,
        attack=agent.attributes.attack,
        defense=agent.attributes.defense,
        speed=agent.attributes.speed,
        move_range=agent.attributes.move_range,
        attack_range=agent.attributes.attack_range,
        status_effects_line=status_effects_line,
        plan_section=plan_section,
        perceptions=perceptions_text,
        memories=format_memories(memories),
        visible_enemies=format_visible_enemies(visible_enemies, social_dispositions),
        available_actions=format_available_actions(can_move, can_attack, can_chat),
    )
