"""Dialogue prompt templates — builds LLM prompts for dialogue exchanges.

Used by cognition/dialogue.py to generate each exchange in a dialogue
session, and to summarize completed sessions into memory nodes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.agent import Agent
    from cognition.memory_stream import MemoryNode


# -- Dialogue response prompt ------------------------------------------------

DIALOGUE_SYSTEM_TEMPLATE = """\
You are {name}, a {combat_class} in a tactical combat arena.

PERSONALITY: {personality}
MORAL ALIGNMENT: {alignment}
BACKSTORY: {backstory}

You are engaged in a conversation during combat. Stay in character. \
Your responses should reflect your personality, memories, and current \
tactical situation. You may propose alliances, threaten, bluff, \
negotiate, or share information — whatever serves your goals.

Respond with a JSON object. No other text. The JSON must have this exact schema:
{{
  "message": "<your spoken response, 1-3 sentences, in character>",
  "continue": <true if you want to keep talking, false to end the conversation>,
  "disposition_shift": <float between -0.3 and +0.3, your internal reaction to this exchange>
}}

The disposition_shift reflects your INTERNAL feelings:
  Positive (up to +0.3): you feel more positively toward them (friendly, trusting, allied)
  Negative (down to -0.3): you feel more negatively (threatened, hostile, suspicious)
  Zero: neutral, no change in feelings\
"""


DIALOGUE_USER_TEMPLATE = """\
SITUATION:
  You are at ({my_x}, {my_y}). HP: {hp}/{max_hp}.
  Round: {round_number}.

YOUR RELATIONSHIP WITH {other_name}:
  Current disposition: {disposition:+.2f} ({disposition_label})
  Trust: {trust:.2f}
{relationship_notes}

MEMORIES ABOUT {other_name}:
{memories}

CONVERSATION SO FAR:
{conversation_history}

{other_name} just said: "{last_message}"

Respond in character. JSON only.\
"""


DIALOGUE_INITIATE_TEMPLATE = """\
SITUATION:
  You are at ({my_x}, {my_y}). HP: {hp}/{max_hp}.
  Round: {round_number}.

YOUR RELATIONSHIP WITH {other_name}:
  Current disposition: {disposition:+.2f} ({disposition_label})
  Trust: {trust:.2f}
{relationship_notes}

MEMORIES ABOUT {other_name}:
{memories}

You have decided to speak to {other_name}. Your initial message idea: "{initial_idea}"

Generate your opening message. JSON only.\
"""


# -- Summary prompt (after dialogue closes) ----------------------------------

SUMMARY_SYSTEM_TEMPLATE = """\
You are {name}. Summarize a conversation you just had during combat.
Write a single sentence from YOUR perspective describing what happened \
and what you learned or decided. Stay in character.

Respond with a JSON object:
{{
  "summary": "<1-2 sentence summary from your perspective>"
}}\
"""

SUMMARY_USER_TEMPLATE = """\
You ({name}) just had a conversation with {other_name}.

The exchange:
{exchange_text}

Summarize this from YOUR perspective. What happened? What did you learn or decide?
JSON only.\
"""


# -- Builder functions -------------------------------------------------------


def build_dialogue_system_prompt(agent: Agent) -> str:
    """Build the system prompt for a dialogue exchange."""
    personality = ", ".join(agent.identity.personality_traits) or "unknown"
    return DIALOGUE_SYSTEM_TEMPLATE.format(
        name=agent.identity.name,
        combat_class=agent.identity.combat_class,
        personality=personality,
        alignment=agent.alignment.label,
        backstory=agent.identity.backstory,
    )


def build_dialogue_response_prompt(
    agent: Agent,
    other_name: str,
    round_number: int,
    my_x: int,
    my_y: int,
    disposition: float,
    trust: float,
    relationship_notes: list[str],
    memories: list[MemoryNode],
    conversation_history: str,
    last_message: str,
) -> str:
    """Build the user prompt for responding in a dialogue."""
    if disposition > 0.5:
        disposition_label = "friendly"
    elif disposition > 0.0:
        disposition_label = "slightly positive"
    elif disposition > -0.3:
        disposition_label = "neutral"
    elif disposition > -0.6:
        disposition_label = "unfriendly"
    else:
        disposition_label = "hostile"

    notes_text = ""
    if relationship_notes:
        notes_text = "  Notes:\n" + "\n".join(
            f"    - {n}" for n in relationship_notes[-5:]
        )

    mem_text = format_dialogue_memories(memories)

    return DIALOGUE_USER_TEMPLATE.format(
        my_x=my_x,
        my_y=my_y,
        hp=agent.attributes.hp,
        max_hp=agent.attributes.max_hp,
        round_number=round_number,
        other_name=other_name,
        disposition=disposition,
        disposition_label=disposition_label,
        trust=trust,
        relationship_notes=notes_text,
        memories=mem_text,
        conversation_history=conversation_history,
        last_message=last_message,
    )


def build_dialogue_initiate_prompt(
    agent: Agent,
    other_name: str,
    round_number: int,
    my_x: int,
    my_y: int,
    disposition: float,
    trust: float,
    relationship_notes: list[str],
    memories: list[MemoryNode],
    initial_idea: str,
) -> str:
    """Build the user prompt for initiating a dialogue."""
    if disposition > 0.5:
        disposition_label = "friendly"
    elif disposition > 0.0:
        disposition_label = "slightly positive"
    elif disposition > -0.3:
        disposition_label = "neutral"
    elif disposition > -0.6:
        disposition_label = "unfriendly"
    else:
        disposition_label = "hostile"

    notes_text = ""
    if relationship_notes:
        notes_text = "  Notes:\n" + "\n".join(
            f"    - {n}" for n in relationship_notes[-5:]
        )

    mem_text = format_dialogue_memories(memories)

    return DIALOGUE_INITIATE_TEMPLATE.format(
        my_x=my_x,
        my_y=my_y,
        hp=agent.attributes.hp,
        max_hp=agent.attributes.max_hp,
        round_number=round_number,
        other_name=other_name,
        disposition=disposition,
        disposition_label=disposition_label,
        trust=trust,
        relationship_notes=notes_text,
        memories=mem_text,
        initial_idea=initial_idea or "I want to talk to them",
    )


def build_summary_prompts(
    agent: Agent,
    other_name: str,
    exchange_text: str,
) -> tuple[str, str]:
    """Build system + user prompts for post-dialogue summary."""
    system = SUMMARY_SYSTEM_TEMPLATE.format(name=agent.identity.name)
    user = SUMMARY_USER_TEMPLATE.format(
        name=agent.identity.name,
        other_name=other_name,
        exchange_text=exchange_text,
    )
    return system, user


def format_dialogue_memories(memories: list[MemoryNode]) -> str:
    """Format memories relevant to the dialogue partner."""
    if not memories:
        return "  (no relevant memories about them)"
    lines = []
    for i, m in enumerate(memories, 1):
        lines.append(f"  {i}. [turn {m.turn_created}] {m.description}")
    return "\n".join(lines)


def format_exchange_history(
    exchanges: list[tuple[str, str]],
) -> str:
    """Format a list of (speaker_name, message) pairs as conversation text."""
    if not exchanges:
        return "  (conversation just starting)"
    lines = []
    for speaker, msg in exchanges:
        lines.append(f'  {speaker}: "{msg}"')
    return "\n".join(lines)
