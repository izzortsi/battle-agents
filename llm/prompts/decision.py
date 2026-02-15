"""Decision prompt template — builds the LLM prompt for combat action selection.

The prompt gives the agent its identity, current state, perceptions,
retrieved memories, and the available action space, then asks for a JSON
action response.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from world.alliance_resolver import AllianceStatus

if TYPE_CHECKING:
    from agent.agent import Agent
    from cognition.memory_stream import MemoryNode


# -- Per-pattern targeting tips shown next to each AoE ability ----------------

_AOE_TIPS: dict[str, str] = {
    "line": (
        "Fires 5 tiles in a straight line FROM YOU toward the target "
        "(hits at distance 1, 2, 3, 4, 5 from you). Move so the target is "
        "within 5 tiles on a cardinal axis to ensure they are on the line."
    ),
    "cross": (
        "Hits a + shape (5 tiles) centered on the target. "
        "The target is always hit; enemies adjacent to them are also hit."
    ),
    "radius": (
        "Hits a 3x3 area (9 tiles) centered on the target. "
        "The target is always hit; all agents within 1 tile are also hit."
    ),
    "cone": (
        "Fan shape from you toward the target: 1-wide near you, "
        "3-wide at the target's distance. Stand close and aim through clusters."
    ),
}

# -- System prompt (character sheet + rules) --------------------------------

SYSTEM_TEMPLATE = """\
You are {name}, a {combat_class} in a dangerous combat arena. Combat is \
inevitable, and only the strongest or most cunning will survive. Alliances \
are possible but fragile — trust must be earned through actions, not words \
alone. Betrayal is always a risk. Stay alert.

PERSONALITY: {personality}
BACKSTORY: {backstory}
{world_lore_section}

You must stay in character at all times. Your decisions should reflect your \
personality, your memories, your relationships, and your tactical assessment. \
Engage threats aggressively, but consider who your real enemies are. The \
disposition shown for each combatant reflects your relationship — allies \
deserve caution before attacking, enemies deserve steel. Standing around \
passively will get you killed.

YOUR COMBAT PROFILE:
- Damage type: {damage_type} (you deal {damage_type} damage based on your {primary_stat} stat)
- Attack range: {attack_range} tiles (Manhattan distance)
- Accuracy depends on your HIT vs enemy SPD — low accuracy means you may miss
- You can land critical hits (chance scales with your SPD)
- Enemies may counter-attack if you miss or they are skilled (scales with their HIT)

COMBAT RULES:
- You are on a 2D tile grid. Coordinates are (x, y). Some tiles are impassable \
(pillars, walls, furniture) — you cannot move through them.
- Each turn you choose a PRIMARY action: attack, defend, ability, or wait.
- You may also MOVE before OR after your primary action by including "target_tile". \
Movement is FREE — you choose whether to move first then act, or act first then \
reposition. Set "move_order" to "before" (default) or "after". \
You MUST pick a tile from the MOVE options listed under AVAILABLE ACTIONS — \
those are the passable, unoccupied tiles within your move range.
- ATTACK is your basic attack. You can only attack targets within your attack \
range ({attack_range} tiles, Manhattan distance). Attacks can MISS, CRIT, or be COUNTERED. \
You can ONLY attack targets listed under "ATTACK targets" — those are in range. \
If no targets are in range, MOVE closer this turn and WAIT, CHAT, or DEFEND; attack next turn.
- ABILITY uses a special ability (costs mana, has cooldown). Abilities can deal \
damage, apply status effects, heal, or buff. Include "ability_name" and \
"target_agent" (omit target_agent for self-targeting abilities like \
self-heals/self-buffs). Ally-targeting abilities (marked [ALLY]) let you heal \
or buff an allied combatant — provide their agent_id as target_agent.
- AoE PATTERNS — abilities hit multiple tiles depending on their pattern:
  * single: hits only the target's tile.
  * line: hits 5 tiles in a straight line FROM YOU toward the target (tiles at \
distance 1, 2, 3, 4, 5 from you along the dominant axis). The TARGET is hit \
ONLY if they are within 5 tiles of you on a cardinal line. Position yourself \
so the target falls on the line.
  * cross: hits a + shape (5 tiles) centered ON the target.
  * radius: hits a 3x3 area (9 tiles) centered ON the target.
  * cone: hits a fan shape from you toward the target, 1-wide near you and \
3-wide at the target's distance.
- WARNING: AoE abilities hit ALL agents on affected tiles — including your \
ALLIES. Check ally positions before using AoE. If an ally is adjacent to your \
target, prefer a single-target attack or reposition first.
- DEFEND raises your defense for one turn (diminishing returns if used repeatedly). \
Use DEFEND only when badly wounded and enemies are far away.
- WAIT is almost never correct. Only wait if you have a very specific tactical reason.
- You may send a brief chat alongside any action. Chat is for taunts, threats, \
alliance offers, coordination, or warnings. Use it when relationships matter — \
but don't waste turns talking when you should be fighting.

PRIORITY ORDER: Ability (if in range, move to reposition first) > Attack \
threats/enemies (if in range) > Move toward enemies + Wait/Chat/Defend (if out of range) > \
Defend (if hurt) > Chat (if socially useful). \
Avoid attacking allies unless they betray you. NEVER attack or use abilities on \
targets not listed under ATTACK targets or ABILITY options — they are out of range.

Respond with a JSON object. No other text. The JSON must have this exact schema:
{{
  "reasoning": "<your internal tactical reasoning, 1-3 sentences, in character>",
  "action": "<one of: attack, defend, ability, wait>",
  "target_tile": "<(x, y) format, optional — MUST be one of the listed MOVE tiles>",
  "move_order": "<'before' or 'after', optional — when to move relative to your action, default 'before'>",
  "target_agent": "<agent_id, required for attack/ability targeting an enemy, omit for self-targeting abilities>",
  "ability_name": "<name of ability, required for ability action, omit otherwise>",
  "chat_target": "<agent_id of who to talk to, optional>",
  "chat_message": "<message text, optional>"
}}
"""


# -- User prompt (situation + perceptions + memories) -----------------------

USER_TEMPLATE = """\
ROUND {round_number}, YOUR TURN.

YOUR STATUS:
  Position: ({my_x}, {my_y})
  HP: {hp}/{max_hp}  |  Mana: {mana}/{max_mana}
  ATK: {atk}  |  MGK: {mgk}  |  SPD: {spd}  |  CON: {con}  |  HIT: {hit}
  Damage type: {damage_type}  |  Phys Def: {phys_def}  |  Mag Def: {mag_def}
  Move range: {move_range}  |  Attack range: {attack_range}
{status_effects_line}
{abilities_section}
{plan_section}
{urgency_section}
CURRENT PERCEPTIONS:
{perceptions}

RELEVANT MEMORIES:
{memories}

COMBATANTS YOU CAN SEE:
{visible_enemies}
{eliminated_section}
AVAILABLE ACTIONS:
{available_actions}

REMEMBER: Engage threats aggressively. Each combatant is labelled ALLIED, \
NEUTRAL, or HOSTILE — this reflects mutual standing, not just your feelings. \
Attack HOSTILE and NEUTRAL threats, but ONLY if they appear under ATTACK targets \
or ABILITY options (meaning they are in range). If no enemies are in range, \
MOVE toward them (pick a tile from the MOVE list) and WAIT, CHAT, or DEFEND — do NOT attempt \
to attack out-of-range targets. Do NOT attack ALLIED combatants unless \
they betray you. Use abilities when impactful — but beware AoE friendly fire \
on allies. Include target_tile to move before or after your action \
(set move_order to "before" or "after"). \
Defend only if critically wounded. Chat to coordinate with allies or intimidate foes.
Choose your action. Respond with JSON only."""


# -- Bonus action prompt addendum -------------------------------------------

BONUS_ACTION_ADDENDUM = """\

*** BONUS ACTION ***
Your exceptional speed grants you a FREE extra action this round!
You may MOVE, ATTACK, DEFEND, or CHAT — but you may NOT use abilities.
This is a bonus action, not your main turn. Make the most of it."""


# -- Builder functions ------------------------------------------------------


def build_system_prompt(agent: Agent, world_lore: str = "") -> str:
    """Build the system prompt from an agent's identity and attributes."""
    personality = ", ".join(agent.identity.personality_traits) or "unknown"
    damage_type = agent.attributes.damage_type
    if world_lore:
        world_lore_section = f"\nWORLD LORE:\n{world_lore}\n"
    else:
        world_lore_section = ""
    return SYSTEM_TEMPLATE.format(
        name=agent.identity.name,
        combat_class=agent.identity.combat_class,
        personality=personality,
        backstory=agent.identity.backstory,
        attack_range=agent.attributes.attack_range,
        damage_type=damage_type,
        primary_stat="ATK" if damage_type == "physical" else "MGK",
        world_lore_section=world_lore_section,
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


def format_abilities(abilities: list[dict], mana: int) -> str:
    """Format the agent's abilities for the user prompt.

    Shows each ability's key stats, cooldown status, and tactical hints.
    """
    if not abilities:
        return ""
    lines = ["YOUR ABILITIES:"]
    for a in abilities:
        name = a.get("name", "?")
        damage = a.get("damage", 0)
        ab_range = a.get("range", 1)
        mana_cost = a.get("mana_cost", 0)
        pattern = a.get("aoe_pattern", "single")
        cooldown = a.get("cooldown", 0)
        current_cd = a.get("current_cd", 0)
        desc = a.get("description", "").strip()
        hint = a.get("tactical_hint", "").strip()

        # Status
        if current_cd > 0:
            cd_status = f"ON COOLDOWN ({current_cd} turns)"
        elif mana_cost > mana:
            cd_status = f"NOT ENOUGH MANA (need {mana_cost})"
        else:
            cd_status = "READY"

        lines.append(f"  [{name}] {cd_status}")
        lines.append(
            f"    Damage: {damage} | Range: {ab_range} | Mana: {mana_cost} | Pattern: {pattern} | Cooldown: {cooldown}"
        )
        if pattern != "single":
            aoe_tip = _AOE_TIPS.get(
                pattern, "AoE — hits multiple tiles around the target."
            )
            lines.append(
                f"    *** AoE ({pattern}): {aoe_tip} Hits ALL agents in area — check ally positions! ***"
            )
        if desc:
            lines.append(f"    What: {desc}")
        if hint:
            lines.append(f"    Hint: {hint}")

        effects = a.get("effects", [])
        if effects:
            eff_parts = []
            for e in effects:
                etype = e.get("type", "?")
                dur = e.get("duration", 1)
                mag = e.get("magnitude", 0)
                tgt = e.get("target", "enemy")
                cat = e.get("category", "debuff")
                eff_parts.append(f"{etype} ({cat}, {tgt}, {dur}t, mag={mag})")
            lines.append(f"    Effects: {'; '.join(eff_parts)}")
    return "\n".join(lines)


def format_visible_enemies(
    enemies: list[dict],
    social_dispositions: dict[str, float] | None = None,
    alliance_statuses: dict[str, AllianceStatus] | None = None,
) -> str:
    """Format visible enemy information.

    Each dict: {name, agent_id, x, y, distance, hp, max_hp, damage_type, phys_def, mag_def}
    social_dispositions: optional map of agent_id -> disposition float.
    alliance_statuses: optional map of agent_id -> AllianceStatus (mutual).
    """
    if not enemies:
        return "  (none visible)"
    lines = []
    for e in enemies:
        hp_pct = int(100 * e["hp"] / e["max_hp"]) if e["max_hp"] > 0 else 0
        dmg_type = e.get("damage_type", "physical")
        phys_def = e.get("phys_def", "?")
        mag_def = e.get("mag_def", "?")

        # Skill-oriented range tags
        reachable = e.get("reachable_by", [])
        if reachable:
            range_str = f"reachable by: {', '.join(reachable)}"
        else:
            range_str = "OUT OF RANGE (move closer)"

        disp_str = ""
        if alliance_statuses and e["agent_id"] in alliance_statuses:
            status = alliance_statuses[e["agent_id"]]
            # Use formal alliance status as the primary label
            d = (
                social_dispositions.get(e["agent_id"], 0.0)
                if social_dispositions
                else 0.0
            )
            disp_str = f" [{status.value.upper()} | disposition: {d:+.2f}]"
        elif social_dispositions and e["agent_id"] in social_dispositions:
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
            disp_str = f" [{label.upper()} | disposition: {d:+.2f}]"
        lines.append(
            f"  - {e['name']} ({e['agent_id']}) at ({e['x']}, {e['y']}), "
            f"distance {e['distance']}, HP {e['hp']}/{e['max_hp']} ({hp_pct}%), "
            f"deals {dmg_type} dmg, pDef {phys_def} / mDef {mag_def} "
            f"| {range_str}{disp_str}"
        )
    return "\n".join(lines)


def format_eliminated(eliminated: list[dict] | None) -> str:
    """Format the list of eliminated combatants for the prompt.

    Each dict: {name, combat_class, killer, method, round}
    """
    if not eliminated:
        return ""
    lines = ["\nELIMINATED (dead — do NOT target these agents):"]
    for e in eliminated:
        lines.append(
            f"  - {e['name']} ({e['combat_class']}) — killed by {e['killer']} "
            f"using {e['method']} in round {e['round']}"
        )
    return "\n".join(lines)


def format_available_actions(
    can_move: list[str],
    can_attack: list[str],
    can_chat: list[str],
    can_ability: list[str] | None = None,
) -> str:
    """Format the set of available actions for the prompt."""
    lines = []
    if can_move:
        # Show all move options so the LLM picks only valid tiles
        lines.append(
            f"  MOVE (free, before or after your action): {', '.join(can_move)}"
        )
    if can_ability:
        lines.append(f"  ABILITY options: {', '.join(can_ability)}")
    if can_attack:
        lines.append(f"  ATTACK targets: {', '.join(can_attack)}")
    lines.append("  DEFEND (raise defense this turn)")
    lines.append("  WAIT (do nothing)")
    if can_chat:
        lines.append(f"  CHAT (combine with any action): {', '.join(can_chat)}")
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
    urgency_text: str = "",
    can_ability: list[str] | None = None,
    alliance_statuses: dict[str, AllianceStatus] | None = None,
    eliminated: list[dict] | None = None,
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

    if urgency_text:
        urgency_section = f"\n*** URGENT: {urgency_text} ***\n"
    else:
        urgency_section = ""

    abilities_section = format_abilities(
        agent.attributes.abilities, agent.attributes.mana
    )

    return USER_TEMPLATE.format(
        round_number=round_number,
        my_x=my_x,
        my_y=my_y,
        hp=agent.attributes.hp,
        max_hp=agent.attributes.max_hp,
        mana=agent.attributes.mana,
        max_mana=agent.attributes.max_mana,
        atk=agent.attributes.atk,
        mgk=agent.attributes.mgk,
        spd=agent.attributes.spd,
        con=agent.attributes.con,
        hit=agent.attributes.hit,
        damage_type=agent.attributes.damage_type,
        phys_def=agent.attributes.phys_def,
        mag_def=agent.attributes.mag_def,
        move_range=agent.attributes.move_range,
        attack_range=agent.attributes.attack_range,
        status_effects_line=status_effects_line,
        abilities_section=abilities_section,
        plan_section=plan_section,
        urgency_section=urgency_section,
        perceptions=perceptions_text,
        memories=format_memories(memories),
        visible_enemies=format_visible_enemies(
            visible_enemies, social_dispositions, alliance_statuses
        ),
        eliminated_section=format_eliminated(eliminated),
        available_actions=format_available_actions(
            can_move, can_attack, can_chat, can_ability
        ),
    )
