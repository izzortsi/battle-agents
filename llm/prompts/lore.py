"""Lore generation prompt templates.

Generates world lore/backstory that contextualises the combat arena.
The lore is injected into agent memories and decision prompts.
"""

from __future__ import annotations

SYSTEM_TEMPLATE = """\
You are a worldbuilder creating the setting for a tactical combat arena.
Given a set of characters and an optional user prompt, generate rich, \
concise world lore that explains WHY these characters are fighting.

Your lore should include:
- A brief world description (2-3 sentences about the setting)
- Key facts about the arena or world (3-5 bullet points)
- Character connections — how the characters relate to each other \
  (rivalries, alliances, grudges, prophecies)

Keep the total output under 300 words. Be dramatic and evocative but concise.
The lore should feel like it could influence combat decisions — characters \
should have personal stakes in the outcome.

Respond with a JSON object:
{
  "world_description": "<2-3 sentences describing the setting>",
  "key_facts": ["<fact 1>", "<fact 2>", ...],
  "character_connections": [
    {"characters": ["<name1>", "<name2>"], "connection": "<description>"},
    ...
  ]
}
"""

USER_TEMPLATE = """\
CHARACTERS IN THIS BATTLE:
{characters_block}

{user_lore_prompt}
Generate world lore for this battle. Respond with JSON only."""


def build_characters_block(characters: list[dict]) -> str:
    """Format character summaries for the lore prompt.

    Each dict should have: name, combat_class, backstory, personality_traits.
    """
    lines = []
    for c in characters:
        name = c.get("name", "Unknown")
        cls = c.get("combat_class", "unknown")
        backstory = c.get("backstory", "No backstory.")
        traits = c.get("personality_traits", [])
        traits_str = ", ".join(traits) if traits else "unknown"
        lines.append(
            f"- {name} ({cls}): {backstory}\n"
            f"  Personality: {traits_str}"
        )
    return "\n".join(lines)


def build_lore_prompts(
    characters: list[dict],
    user_prompt: str = "",
) -> tuple[str, str]:
    """Build system + user prompts for lore generation.

    Returns (system_prompt, user_prompt).
    """
    characters_block = build_characters_block(characters)

    if user_prompt:
        user_lore_prompt = f"USER'S WORLD SETTING:\n{user_prompt}\n"
    else:
        user_lore_prompt = ""

    user = USER_TEMPLATE.format(
        characters_block=characters_block,
        user_lore_prompt=user_lore_prompt,
    )

    return SYSTEM_TEMPLATE, user
