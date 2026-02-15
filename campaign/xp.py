"""XP awards and LLM-driven level-up.

XP sources per battle:
    - Kill:     50 XP per enemy killed
    - Damage:   1 XP per point of damage dealt
    - Survival: 25 XP for surviving the battle
    - Victory:  100 XP for being on the winning side

Level thresholds:
    Level N → N+1 requires ``N * 100`` XP.
    (L1→L2 = 100, L2→L3 = 200, ..., L9→L10 = 900)

On level-up the LLM picks 2 stats to increase by +1, based on the
character's class and combat history.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from campaign.models import BattleRecord, RosterEntry
from llm.adapter import LLMAdapter
from llm.json_utils import extract_json

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# XP constants
# ---------------------------------------------------------------------------

XP_PER_KILL = 50
XP_PER_DAMAGE = 1
XP_SURVIVAL = 25
XP_VICTORY = 100


# ---------------------------------------------------------------------------
# XP award calculation
# ---------------------------------------------------------------------------


@dataclass
class XPBreakdown:
    """Itemised XP award for one agent."""

    agent_id: str
    kills: int = 0
    damage_dealt: int = 0
    survived: bool = False
    won: bool = False

    @property
    def total(self) -> int:
        xp = self.kills * XP_PER_KILL
        xp += self.damage_dealt * XP_PER_DAMAGE
        if self.survived:
            xp += XP_SURVIVAL
        if self.won:
            xp += XP_VICTORY
        return xp


def compute_xp_awards(
    alive_ids: set[str],
    winner_ids: list[str],
    kill_counts: dict[str, int],
    damage_dealt: dict[str, int],
    all_ids: set[str],
) -> dict[str, XPBreakdown]:
    """Compute XP breakdown for every agent that participated.

    Parameters
    ----------
    alive_ids : set of agent_ids still alive at battle end
    winner_ids : agent_ids on the winning side
    kill_counts : agent_id -> number of kills
    damage_dealt : agent_id -> total damage dealt
    all_ids : every agent that participated (alive or dead)
    """
    winner_set = set(winner_ids)
    awards: dict[str, XPBreakdown] = {}
    for aid in all_ids:
        awards[aid] = XPBreakdown(
            agent_id=aid,
            kills=kill_counts.get(aid, 0),
            damage_dealt=damage_dealt.get(aid, 0),
            survived=aid in alive_ids,
            won=aid in winner_set,
        )
    return awards


# ---------------------------------------------------------------------------
# LLM-driven level-up
# ---------------------------------------------------------------------------

_LEVEL_UP_SYSTEM = """\
You are a game designer deciding how a character levels up after a battle.

Given the character's current stats and combat class, pick exactly 2 stats \
to increase by +1 each. The stats should make sense for the character's \
class and fighting style.

Available stats: atk, mgk, spd, con, hit

Respond with a JSON object only. No other text. Schema:
{
  "stat_1": "<stat name>",
  "stat_2": "<stat name>",
  "reasoning": "<1 sentence explaining the growth>"
}"""


def _build_level_up_user(entry: RosterEntry) -> str:
    return (
        f"Character: {entry.name}\n"
        f"Class: {entry.combat_class}\n"
        f"Level: {entry.level} → {entry.level + 1}\n"
        f"Current stats: ATK={entry.atk}, MGK={entry.mgk}, "
        f"SPD={entry.spd}, CON={entry.con}, HIT={entry.hit}\n\n"
        f"Pick 2 stats to increase by +1."
    )


_VALID_STATS = {"atk", "mgk", "spd", "con", "hit"}


def llm_level_up(entry: RosterEntry, llm: LLMAdapter) -> dict[str, int]:
    """Ask the LLM which 2 stats to grow.

    Returns a dict like ``{"atk": 1, "spd": 1}``.
    Falls back to class-based defaults if the LLM fails.
    """
    try:
        raw = llm.complete(
            system=_LEVEL_UP_SYSTEM,
            user=_build_level_up_user(entry),
            max_tokens=128,
            temperature=0.5,
            response_format="json",
        )
        data = extract_json(raw)
        stat1 = data.get("stat_1", "").lower().strip()
        stat2 = data.get("stat_2", "").lower().strip()
        reasoning = data.get("reasoning", "")
        if stat1 in _VALID_STATS and stat2 in _VALID_STATS:
            log.info(
                "LLM level-up for %s: +1 %s, +1 %s (%s)",
                entry.name,
                stat1,
                stat2,
                reasoning,
            )
            increases: dict[str, int] = {}
            increases[stat1] = increases.get(stat1, 0) + 1
            increases[stat2] = increases.get(stat2, 0) + 1
            return increases
    except Exception:
        log.warning(
            "LLM level-up failed for %s, using fallback.", entry.name, exc_info=True
        )

    return _fallback_level_up(entry.combat_class)


def _fallback_level_up(combat_class: str) -> dict[str, int]:
    """Deterministic fallback: pick 2 stats based on class archetype."""
    slug = combat_class.lower()
    if any(k in slug for k in ("mage", "wizard", "sorcerer", "witch")):
        return {"mgk": 1, "con": 1}
    if any(k in slug for k in ("rogue", "assassin", "thief")):
        return {"spd": 1, "hit": 1}
    if any(k in slug for k in ("healer", "cleric", "priest")):
        return {"mgk": 1, "con": 1}
    if any(k in slug for k in ("ranger", "archer", "gunslinger")):
        return {"hit": 1, "spd": 1}
    # Default warrior/berserker/fighter
    return {"atk": 1, "con": 1}
