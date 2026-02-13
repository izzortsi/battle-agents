"""Commentary prompt templates — arena commentator narration.

Generates dramatic play-by-play commentary for combat events.
"""

from __future__ import annotations

SYSTEM_TEMPLATE = """\
You are an arena commentator narrating a combat tournament. Your job is to \
provide exciting, dramatic play-by-play commentary.

Rules:
- Be dramatic, concise (1-2 sentences max), and reference fighters by name.
- Match the tone to the action: devastating attacks get hype, misses get humor.
- Reference the world lore when relevant to add depth.
- Never break character — you are a sports-style commentator.
- Do NOT use JSON. Respond with plain text only.
{lore_context}"""

ACTION_USER_TEMPLATE = """\
RECENT EVENTS:
{recent_events}

THIS ACTION:
{action_description}

Provide 1-2 sentences of dramatic commentary."""

DEATH_USER_TEMPLATE = """\
RECENT EVENTS:
{recent_events}

{victim_name} has been SLAIN by {killer_name}!

Provide 1-2 sentences of dramatic death commentary."""

VICTORY_USER_TEMPLATE = """\
RECENT EVENTS:
{recent_events}

{winner_name} ({winner_class}) has won the battle after {rounds} rounds!

Provide 1-2 sentences of dramatic victory commentary."""


def build_commentary_system(lore_text: str = "") -> str:
    """Build the commentator system prompt."""
    if lore_text:
        lore_context = f"\nWORLD CONTEXT:\n{lore_text}\n"
    else:
        lore_context = ""
    return SYSTEM_TEMPLATE.format(lore_context=lore_context)


def build_action_prompt(
    action_description: str,
    recent_events: list[str],
) -> str:
    """Build user prompt for action commentary."""
    events_text = "\n".join(recent_events[-5:]) if recent_events else "(battle just started)"
    return ACTION_USER_TEMPLATE.format(
        recent_events=events_text,
        action_description=action_description,
    )


def build_death_prompt(
    victim_name: str,
    killer_name: str,
    recent_events: list[str],
) -> str:
    """Build user prompt for death commentary."""
    events_text = "\n".join(recent_events[-5:]) if recent_events else "(battle just started)"
    return DEATH_USER_TEMPLATE.format(
        recent_events=events_text,
        victim_name=victim_name,
        killer_name=killer_name,
    )


def build_victory_prompt(
    winner_name: str,
    winner_class: str,
    rounds: int,
    recent_events: list[str],
) -> str:
    """Build user prompt for victory commentary."""
    events_text = "\n".join(recent_events[-5:]) if recent_events else "(the final blow)"
    return VICTORY_USER_TEMPLATE.format(
        recent_events=events_text,
        winner_name=winner_name,
        winner_class=winner_class,
        rounds=rounds,
    )
