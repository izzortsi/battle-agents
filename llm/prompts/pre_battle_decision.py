"""Pre-battle decision prompt template — social-phase compound actions.

During the pre-battle phase agents choose a **primary action** (move or wait)
AND may optionally initiate a **free chat** in the same tick.  There is no
combat (no attack/defend).  The emphasis is on social interaction: approaching
other agents, initiating conversations, forming alliances or enmities.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.agent import Agent
    from cognition.memory_stream import MemoryNode


# -- System prompt (character sheet + social rules) --------------------------

SYSTEM_TEMPLATE = """\
You are {name}, a {combat_class} preparing for an upcoming battle.

PERSONALITY: {personality}
BACKSTORY: {backstory}

Right now you are in a tavern — a social gathering BEFORE combat begins. \
There is no fighting yet. Warriors, mages, and mercenaries mingle around \
tables and the bar counter. This is your chance to talk to other warriors, \
form alliances, gather information, size up opponents, and make plans. \
The walls are close, the ale is flowing, and everyone knows the arena awaits.

You must stay in character at all times. Your decisions should reflect your \
personality traits, your memories, and your social goals.

RULES:
- You are on a 2D tile grid. Coordinates are (x, y).
- Each tick you choose a PRIMARY ACTION plus an optional free CHAT.
- Primary actions: MOVE (walk to an adjacent tile) or WAIT (observe).
- CHAT is FREE — it does not cost your action. You may chat AND move/wait \
in the same tick. Chatting is the main activity of this phase.
- There is NO combat in this phase. You cannot attack or defend.

SOCIAL GOALS to consider:
- Seek out agents you have history with (allies, rivals, unknowns)
- Gather information about other agents' intentions
- Form alliances with those who share your interests
- Identify potential threats for the coming battle
- Share or withhold information strategically based on your personality

Respond with a JSON object. No other text. The JSON must have this exact schema:
{{
  "reasoning": "<your social reasoning, 1-3 sentences, in character>",
  "action": "<primary action: move or wait>",
  "target_tile": "<x_y format, required for move, omit otherwise>",
  "chat_target": "<agent_id of who to talk to, omit if not chatting>",
  "chat_message": "<what you say to start the conversation, omit if not chatting>"
}}
"""


# -- User prompt (situation + perceptions + memories) ------------------------

USER_TEMPLATE = """\
TAVERN — TICK {tick_number} of {total_ticks}. Combat in the arena begins after the social phase.

YOUR STATUS:
  Position: ({my_x}, {my_y})
  Combat class: {combat_class}  |  Damage type: {damage_type}
  HP: {hp}/{max_hp}  |  ATK: {atk}  |  MGK: {mgk}  |  SPD: {spd}  |  CON: {con}  |  HIT: {hit}
{plan_section}
PEOPLE YOU CAN SEE:
{visible_agents}

CURRENT PERCEPTIONS:
{perceptions}

RELEVANT MEMORIES:
{memories}

AVAILABLE ACTIONS:
{available_actions}

Think about who you want to talk to AND where you want to move. \
You can do both in one tick. Respond with JSON only."""


# -- Builder functions -------------------------------------------------------


def build_pre_battle_system_prompt(agent: Agent) -> str:
    """Build the system prompt for pre-battle social decisions."""
    personality = ", ".join(agent.identity.personality_traits) or "unknown"
    return SYSTEM_TEMPLATE.format(
        name=agent.identity.name,
        combat_class=agent.identity.combat_class,
        personality=personality,
        backstory=agent.identity.backstory,
    )


def format_pre_battle_memories(memories: list[MemoryNode]) -> str:
    """Format retrieved memories for the pre-battle prompt."""
    if not memories:
        return "  (no relevant memories)"
    lines = []
    for i, m in enumerate(memories, 1):
        turn_label = f"[tick {m.turn_created}]"
        lines.append(f"  {i}. {turn_label} {m.description}")
    return "\n".join(lines)


def format_visible_agents(
    agents: list[dict],
    social_dispositions: dict[str, float] | None = None,
) -> str:
    """Format visible agents for the pre-battle prompt.

    Each dict: {name, agent_id, x, y, distance, combat_class}
    social_dispositions: optional map of agent_id -> disposition float.
    """
    if not agents:
        return "  (nobody nearby)"
    lines = []
    for a in agents:
        disp_str = ""
        if social_dispositions and a["agent_id"] in social_dispositions:
            d = social_dispositions[a["agent_id"]]
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
            f"  - {a['name']} ({a['agent_id']}), {a.get('combat_class', '?')}, "
            f"at ({a['x']}, {a['y']}), distance {a['distance']}{disp_str}"
        )
    return "\n".join(lines)


def format_pre_battle_actions(
    can_move: list[str],
    can_chat: list[str],
) -> str:
    """Format available pre-battle actions."""
    lines = []
    lines.append("  PRIMARY ACTION (choose one):")
    if can_move:
        display = can_move[:6]
        extra = f" (+{len(can_move) - 6} more)" if len(can_move) > 6 else ""
        lines.append(f"    MOVE to tiles: {', '.join(display)}{extra}")
    lines.append("    WAIT (observe and do nothing)")
    lines.append("")
    lines.append("  FREE CHAT (optional, can combine with move/wait):")
    if can_chat:
        lines.append(f"    Talk to: {', '.join(can_chat)}")
    else:
        lines.append("    (nobody in range to chat with)")
    return "\n".join(lines)


def build_pre_battle_user_prompt(
    agent: Agent,
    tick_number: int,
    total_ticks: int,
    my_x: int,
    my_y: int,
    perceptions_text: str,
    memories: list[MemoryNode],
    visible_agents: list[dict],
    can_move: list[str],
    can_chat: list[str],
    current_plan: str = "",
    social_dispositions: dict[str, float] | None = None,
) -> str:
    """Build the user prompt for pre-battle social decisions."""
    if current_plan:
        plan_section = f"\nYOUR CURRENT SOCIAL PLAN:\n  {current_plan}\n"
    else:
        plan_section = ""

    return USER_TEMPLATE.format(
        tick_number=tick_number,
        total_ticks=total_ticks,
        my_x=my_x,
        my_y=my_y,
        combat_class=agent.identity.combat_class,
        damage_type=agent.attributes.damage_type,
        hp=agent.attributes.hp,
        max_hp=agent.attributes.max_hp,
        atk=agent.attributes.atk,
        mgk=agent.attributes.mgk,
        spd=agent.attributes.spd,
        con=agent.attributes.con,
        hit=agent.attributes.hit,
        plan_section=plan_section,
        perceptions=perceptions_text,
        memories=format_pre_battle_memories(memories),
        visible_agents=format_visible_agents(visible_agents, social_dispositions),
        available_actions=format_pre_battle_actions(can_move, can_chat),
    )
