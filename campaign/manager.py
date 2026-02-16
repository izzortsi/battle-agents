"""Campaign manager — orchestrates the battle → rewards → persist loop.

Coordinates:
    - Building Agent objects from the persistent roster
    - Restoring memories and social relationships before each battle
    - Collecting battle results (kills, damage, survival, victory)
    - Computing XP awards and processing level-ups
    - Compressing memories and serialising social state for carry-over
    - Persisting everything to SQLite

Usage::

    db = CampaignDB()
    mgr = CampaignManager(db, campaign_id=1)

    # Before a battle:
    agents = mgr.build_agents()            # -> list[Agent] with restored state
    mgr.restore_agent_state(agents, cognitive_loop)  # inject memories + social

    # After a battle:
    mgr.process_battle_results(env, cognitive_loop, llm)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agent.agent import Agent
from agent.attributes import Attributes
from agent.identity import Identity
from agent.moral_alignment import MoralAlignment
from campaign.memory_compression import compress_memories, restore_memories
from campaign.models import (
    BattleRecord,
    RosterEntry,
    SerializedRelationship,
)
from campaign.persistence import CampaignDB
from campaign.xp import XPBreakdown, compute_xp_awards, llm_level_up

if TYPE_CHECKING:
    from cognition.cognitive_loop import CognitiveLoop
    from llm.adapter import LLMAdapter
    from world.environment import Environment

log = logging.getLogger(__name__)


class CampaignManager:
    """Manages one active campaign's lifecycle."""

    def __init__(self, db: CampaignDB, campaign_id: int) -> None:
        self.db = db
        self.campaign_id = campaign_id
        meta = db.get_campaign(campaign_id)
        if meta is None:
            raise ValueError(f"Campaign {campaign_id} not found")
        self.meta = meta

    # -----------------------------------------------------------------
    # Pre-battle: build agents from roster
    # -----------------------------------------------------------------

    def build_agents(self) -> list[Agent]:
        """Create Agent objects from the alive roster entries.

        Agents have their levelled stats and abilities but fresh
        HP/mana (full heal between battles).
        """
        roster = self.db.load_alive_roster(self.campaign_id)
        agents: list[Agent] = []
        for entry in roster:
            # Derive a label from the persisted float values so __post_init__
            # produces a MoralAlignment close to the saved state.
            _temp_align = MoralAlignment(
                morality=entry.morality, order=entry.order_value
            )
            identity = Identity(
                name=entry.name,
                backstory=entry.backstory,
                personality_traits=list(entry.personality_traits),
                combat_class=entry.combat_class,
                sprite=entry.sprite,
                moral_alignment=_temp_align.label_key,
            )
            # Reset cooldowns on all abilities
            abilities = []
            for ab in entry.abilities:
                ab_copy = dict(ab)
                ab_copy["current_cd"] = 0
                abilities.append(ab_copy)

            attributes = Attributes(
                atk=entry.atk,
                mgk=entry.mgk,
                spd=entry.spd,
                con=entry.con,
                hit=entry.hit,
                attack_range=entry.attack_range,
                abilities=abilities,
            )
            agent = Agent(
                agent_id=entry.agent_id,
                identity=identity,
                attributes=attributes,
            )
            # Restore exact float alignment values (label-based init loses
            # precision from in-battle drift).
            agent.alignment.morality = entry.morality
            agent.alignment.order = entry.order_value
            agents.append(agent)
        log.info(
            "Built %d agents from campaign %d roster.", len(agents), self.campaign_id
        )
        return agents

    def restore_agent_state(
        self, agents: list[Agent], cognitive_loop: CognitiveLoop
    ) -> None:
        """Restore memories and social relationships from the DB.

        Call this after ``build_agents()`` and after registering agents
        with the cognitive loop.
        """
        # Memories
        all_memories = self.db.load_memories(self.campaign_id)
        by_agent: dict[str, list] = {}
        for m in all_memories:
            by_agent.setdefault(m.agent_id, []).append(m)

        for agent in agents:
            mems = by_agent.get(agent.agent_id, [])
            cog_state = cognitive_loop.get_state(agent.agent_id)
            if mems and cog_state is not None:
                stream = cog_state.memory
                restore_memories(stream, mems)
                log.info("Restored %d memories for %s.", len(mems), agent.name)

        # Social relationships
        all_rels = self.db.load_relationships(self.campaign_id)
        by_owner: dict[str, list[SerializedRelationship]] = {}
        for r in all_rels:
            by_owner.setdefault(r.owner_id, []).append(r)

        for agent in agents:
            rels = by_owner.get(agent.agent_id, [])
            for r in rels:
                rel_obj = agent.social.ensure_relationship(r.target_id, r.target_name)
                rel_obj.disposition = r.disposition
                rel_obj.trust = r.trust
                rel_obj.betrayal_count = r.betrayal_count
                rel_obj.alliance_declared = r.alliance_declared
            if rels:
                log.info("Restored %d relationships for %s.", len(rels), agent.name)

    # -----------------------------------------------------------------
    # Post-battle: collect results, award XP, persist
    # -----------------------------------------------------------------

    def process_battle_results(
        self,
        env: Environment,
        cognitive_loop: CognitiveLoop,
        llm: LLMAdapter,
        top_k_memories: int = 20,
    ) -> BattleRecord:
        """Process everything after a battle ends.

        1. Compute XP awards
        2. Apply permadeath
        3. Award XP + process level-ups
        4. Compress and save memories
        5. Save social relationships
        6. Save battle record
        7. Save updated roster

        Returns the ``BattleRecord``.
        """
        battle_num = self.meta.battle_count + 1

        # Gather battle stats
        winner_ids = [a.agent_id for a in (env.get_winners() or [])]
        alive_ids = {a.agent_id for a in env.alive_agents()}
        all_ids = {aid for aid in env.agents}

        # Build kill/damage maps from death_log and action tracking
        kill_counts: dict[str, int] = {}
        death_ids: list[str] = []
        for entry in env.death_log:
            killer = entry.get("killer", "")
            if killer:
                kill_counts[killer] = kill_counts.get(killer, 0) + 1
            death_ids.append(entry["agent_id"])

        # Damage dealt tracking (from environment if available)
        damage_dealt: dict[str, int] = getattr(env, "damage_dealt", {})

        # Compute XP
        xp_map = compute_xp_awards(
            alive_ids, winner_ids, kill_counts, damage_dealt, all_ids
        )
        xp_totals = {aid: bd.total for aid, bd in xp_map.items()}

        # Load and update roster
        roster = self.db.load_roster(self.campaign_id)
        roster_by_id = {r.agent_id: r for r in roster}

        # Apply permadeath
        for aid in death_ids:
            entry = roster_by_id.get(aid)
            if entry:
                entry.alive = False
                log.info("PERMADEATH: %s is eliminated from the campaign.", entry.name)

        # Award XP + level-ups
        level_ups: list[str] = []
        for aid, xp_total in xp_totals.items():
            entry = roster_by_id.get(aid)
            if entry is None:
                continue
            entry.xp += xp_total
            log.info(
                "%s earned %d XP (total: %d/%d).",
                entry.name,
                xp_total,
                entry.xp,
                entry.xp_to_next_level,
            )
            # Process level-ups (could be multiple)
            while entry.can_level_up():
                increases = llm_level_up(entry, llm)
                old_level = entry.level
                entry.apply_level_up(increases)
                log.info(
                    "LEVEL UP! %s: L%d → L%d  (%s)",
                    entry.name,
                    old_level,
                    entry.level,
                    ", ".join(f"+1 {s}" for s in increases),
                )
                level_ups.append(entry.name)

        # Save drifted alignment values to roster
        for aid, agent in env.agents.items():
            entry = roster_by_id.get(aid)
            if entry:
                entry.morality = agent.alignment.morality
                entry.order_value = agent.alignment.order

        # Compress and save memories
        all_compressed = []
        for aid, agent in env.agents.items():
            cog_state = cognitive_loop.get_state(aid)
            if cog_state is not None:
                stream = cog_state.memory
                compressed = compress_memories(aid, stream, top_k=top_k_memories)
                all_compressed.extend(compressed)
        if all_compressed:
            self.db.save_memories(self.campaign_id, all_compressed)
            log.info(
                "Saved %d compressed memories across %d agents.",
                len(all_compressed),
                len({m.agent_id for m in all_compressed}),
            )

        # Save social relationships
        all_rels = []
        for aid, agent in env.agents.items():
            for tid, rel in agent.social.all_relationships().items():
                all_rels.append(
                    SerializedRelationship(
                        owner_id=aid,
                        target_id=tid,
                        target_name=rel.agent_name,
                        disposition=rel.disposition,
                        trust=rel.trust,
                        betrayal_count=rel.betrayal_count,
                        alliance_declared=rel.alliance_declared,
                    )
                )
        if all_rels:
            self.db.save_relationships(self.campaign_id, all_rels)
            log.info("Saved %d relationships.", len(all_rels))

        # Save battle record
        record = BattleRecord(
            battle_num=battle_num,
            winner_ids=winner_ids,
            death_ids=death_ids,
            rounds=getattr(env, "round_number", 0),
            xp_awards=xp_totals,
        )
        self.db.save_battle(self.campaign_id, record)
        self.db.increment_battle_count(self.campaign_id)

        # Save updated roster
        self.db.save_roster(self.campaign_id, roster)

        log.info(
            "Battle %d complete. Winners: %s. Deaths: %s. Level-ups: %s.",
            battle_num,
            winner_ids or "draw",
            death_ids or "none",
            level_ups or "none",
        )

        return record

    # -----------------------------------------------------------------
    # Roster management
    # -----------------------------------------------------------------

    def add_to_roster(self, agent: Agent) -> RosterEntry:
        """Add a new character to the campaign roster."""
        entry = roster_entry_from_agent(agent)
        self.db.save_roster(self.campaign_id, [entry])
        return entry

    def get_roster(self) -> list[RosterEntry]:
        return self.db.load_roster(self.campaign_id)

    def get_alive_roster(self) -> list[RosterEntry]:
        return self.db.load_alive_roster(self.campaign_id)

    def get_battle_history(self) -> list[BattleRecord]:
        return self.db.load_battles(self.campaign_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def roster_entry_from_agent(agent: Agent) -> RosterEntry:
    """Create a RosterEntry from an Agent (for initial roster seeding)."""
    a = agent.attributes
    return RosterEntry(
        agent_id=agent.agent_id,
        name=agent.name,
        combat_class=agent.identity.combat_class,
        sprite=agent.identity.sprite,
        backstory=agent.identity.backstory,
        personality_traits=list(agent.identity.personality_traits),
        atk=a.atk,
        mgk=a.mgk,
        spd=a.spd,
        con=a.con,
        hit=a.hit,
        attack_range=a.attack_range,
        abilities=[dict(ab) for ab in a.abilities],
        morality=agent.alignment.morality,
        order_value=agent.alignment.order,
    )
