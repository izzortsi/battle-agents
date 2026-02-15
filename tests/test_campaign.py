"""Tests for the campaign subsystem — models, persistence, XP, memory compression."""

import json

import pytest

from campaign.models import (
    BattleRecord,
    CampaignMeta,
    RosterEntry,
    SerializedMemory,
    SerializedRelationship,
)
from campaign.persistence import CampaignDB
from campaign.xp import (
    XP_PER_DAMAGE,
    XP_PER_KILL,
    XP_SURVIVAL,
    XP_VICTORY,
    XPBreakdown,
    _fallback_level_up,
    compute_xp_awards,
)
from campaign.memory_compression import compress_memories, restore_memories
from cognition.memory_stream import MemoryStream, MemoryType


# ====================================================================
# Models
# ====================================================================


class TestRosterEntry:
    def test_xp_to_next_level(self):
        e = RosterEntry(agent_id="a", name="A", level=1)
        assert e.xp_to_next_level == 100

    def test_xp_to_next_level_scales(self):
        e = RosterEntry(agent_id="a", name="A", level=5)
        assert e.xp_to_next_level == 500

    def test_can_level_up_false(self):
        e = RosterEntry(agent_id="a", name="A", level=1, xp=50)
        assert not e.can_level_up()

    def test_can_level_up_true(self):
        e = RosterEntry(agent_id="a", name="A", level=1, xp=100)
        assert e.can_level_up()

    def test_apply_level_up(self):
        e = RosterEntry(agent_id="a", name="A", level=1, xp=150, atk=10, spd=10)
        e.apply_level_up({"atk": 1, "spd": 1})
        assert e.level == 2
        assert e.atk == 11
        assert e.spd == 11
        assert e.xp == 50  # 150 - 100

    def test_apply_level_up_stat_cap(self):
        e = RosterEntry(agent_id="a", name="A", level=1, xp=100, atk=30)
        e.apply_level_up({"atk": 1})
        assert e.atk == 30  # capped at 30

    def test_xp_progress(self):
        e = RosterEntry(agent_id="a", name="A", level=1, xp=50)
        assert e.xp_progress == 0.5

    def test_xp_progress_capped(self):
        e = RosterEntry(agent_id="a", name="A", level=1, xp=200)
        assert e.xp_progress == 1.0


class TestBattleRecord:
    def test_defaults(self):
        r = BattleRecord(battle_num=1)
        assert r.winner_ids == []
        assert r.death_ids == []
        assert r.rounds == 0
        assert r.timestamp  # auto-filled


class TestCampaignMeta:
    def test_auto_timestamp(self):
        m = CampaignMeta(name="Test")
        assert m.created_at  # auto-filled


# ====================================================================
# XP
# ====================================================================


class TestXPBreakdown:
    def test_kill_xp(self):
        b = XPBreakdown(agent_id="a", kills=2)
        assert b.total == 2 * XP_PER_KILL

    def test_damage_xp(self):
        b = XPBreakdown(agent_id="a", damage_dealt=30)
        assert b.total == 30 * XP_PER_DAMAGE

    def test_survival_xp(self):
        b = XPBreakdown(agent_id="a", survived=True)
        assert b.total == XP_SURVIVAL

    def test_victory_xp(self):
        b = XPBreakdown(agent_id="a", won=True)
        assert b.total == XP_VICTORY

    def test_combined(self):
        b = XPBreakdown(agent_id="a", kills=1, damage_dealt=20, survived=True, won=True)
        assert b.total == XP_PER_KILL + 20 * XP_PER_DAMAGE + XP_SURVIVAL + XP_VICTORY

    def test_zero(self):
        b = XPBreakdown(agent_id="a")
        assert b.total == 0


class TestComputeXPAwards:
    def test_basic(self):
        awards = compute_xp_awards(
            alive_ids={"a"},
            winner_ids=["a"],
            kill_counts={"a": 1},
            damage_dealt={"a": 10},
            all_ids={"a", "b"},
        )
        assert awards["a"].kills == 1
        assert awards["a"].survived is True
        assert awards["a"].won is True
        assert awards["b"].survived is False
        assert awards["b"].won is False

    def test_draw(self):
        awards = compute_xp_awards(
            alive_ids=set(),
            winner_ids=[],
            kill_counts={},
            damage_dealt={},
            all_ids={"a", "b"},
        )
        for bd in awards.values():
            assert bd.total == 0


class TestFallbackLevelUp:
    def test_warrior(self):
        result = _fallback_level_up("warrior")
        assert "atk" in result
        assert "con" in result

    def test_mage(self):
        result = _fallback_level_up("fire mage")
        assert "mgk" in result

    def test_rogue(self):
        result = _fallback_level_up("rogue")
        assert "spd" in result
        assert "hit" in result

    def test_unknown_defaults_warrior(self):
        result = _fallback_level_up("unknown")
        assert "atk" in result


# ====================================================================
# Memory compression
# ====================================================================


class TestMemoryCompression:
    def _build_stream(self, n: int) -> MemoryStream:
        s = MemoryStream()
        for i in range(n):
            s.add(
                turn=i,
                memory_type=MemoryType.OBSERVATION,
                description=f"Memory {i}",
                poignancy=i + 1,
            )
        return s

    def test_compress_top_k(self):
        stream = self._build_stream(30)
        result = compress_memories("a", stream, top_k=5)
        assert len(result) == 5
        # Highest poignancy should be selected
        poignancies = [m.poignancy for m in result]
        assert max(poignancies) == 30

    def test_compress_empty(self):
        stream = MemoryStream()
        result = compress_memories("a", stream, top_k=5)
        assert result == []

    def test_compress_fewer_than_k(self):
        stream = self._build_stream(3)
        result = compress_memories("a", stream, top_k=10)
        assert len(result) == 3

    def test_reflections_prioritised(self):
        stream = MemoryStream()
        stream.add(
            turn=0, memory_type=MemoryType.OBSERVATION, description="obs", poignancy=10
        )
        stream.add(
            turn=1,
            memory_type=MemoryType.REFLECTION,
            description="ref",
            poignancy=5,
            depth=1,
        )
        result = compress_memories("a", stream, top_k=1)
        # Reflection (depth=1) should be chosen over observation (depth=0)
        assert result[0].memory_type == "reflection"

    def test_restore_memories(self):
        stream = MemoryStream()
        mems = [
            SerializedMemory(
                agent_id="a",
                description="old memory",
                poignancy=7,
                memory_type="observation",
                turn_created=0,
            ),
            SerializedMemory(
                agent_id="a",
                description="old reflection",
                poignancy=9,
                memory_type="reflection",
                turn_created=5,
            ),
        ]
        restore_memories(stream, mems)
        assert len(stream) == 2
        assert stream.importance_accumulator == 0.0  # reset after restore

    def test_restore_round_trip(self):
        # Build -> compress -> restore -> verify content
        stream1 = self._build_stream(10)
        compressed = compress_memories("a", stream1, top_k=3)

        stream2 = MemoryStream()
        restore_memories(stream2, compressed)
        assert len(stream2) == 3
        descriptions = {n.description for n in stream2.all()}
        assert "Memory 9" in descriptions  # highest poignancy


# ====================================================================
# Persistence (SQLite)
# ====================================================================


class TestCampaignDB:
    @pytest.fixture
    def db(self, tmp_path):
        """Create a temporary campaign DB."""
        path = tmp_path / "test.db"
        database = CampaignDB(path)
        yield database
        database.close()

    # -- Campaign CRUD --

    def test_create_campaign(self, db):
        meta = db.create_campaign("Test Campaign")
        assert meta.campaign_id > 0
        assert meta.name == "Test Campaign"
        assert meta.battle_count == 0

    def test_get_campaign(self, db):
        meta = db.create_campaign("Test")
        loaded = db.get_campaign(meta.campaign_id)
        assert loaded is not None
        assert loaded.name == "Test"

    def test_get_campaign_missing(self, db):
        assert db.get_campaign(9999) is None

    def test_list_campaigns(self, db):
        db.create_campaign("A")
        db.create_campaign("B")
        campaigns = db.list_campaigns()
        assert len(campaigns) == 2
        names = {c.name for c in campaigns}
        assert names == {"A", "B"}

    def test_increment_battle_count(self, db):
        meta = db.create_campaign("Test")
        db.increment_battle_count(meta.campaign_id)
        loaded = db.get_campaign(meta.campaign_id)
        assert loaded.battle_count == 1

    def test_delete_campaign(self, db):
        meta = db.create_campaign("Test")
        db.save_roster(
            meta.campaign_id,
            [
                RosterEntry(agent_id="a", name="A"),
            ],
        )
        db.delete_campaign(meta.campaign_id)
        assert db.get_campaign(meta.campaign_id) is None
        assert db.load_roster(meta.campaign_id) == []

    # -- Roster --

    def test_save_load_roster(self, db):
        meta = db.create_campaign("Test")
        roster = [
            RosterEntry(
                agent_id="kael",
                name="Kael",
                combat_class="warrior",
                atk=15,
                mgk=8,
                spd=10,
                con=14,
                hit=12,
                level=2,
                xp=50,
            ),
            RosterEntry(
                agent_id="lyra",
                name="Lyra",
                combat_class="mage",
                atk=8,
                mgk=18,
                spd=12,
                con=9,
                hit=10,
            ),
        ]
        db.save_roster(meta.campaign_id, roster)
        loaded = db.load_roster(meta.campaign_id)
        assert len(loaded) == 2
        kael = next(r for r in loaded if r.agent_id == "kael")
        assert kael.atk == 15
        assert kael.level == 2
        assert kael.xp == 50

    def test_load_alive_roster(self, db):
        meta = db.create_campaign("Test")
        roster = [
            RosterEntry(agent_id="a", name="A", alive=True),
            RosterEntry(agent_id="b", name="B", alive=False),
        ]
        db.save_roster(meta.campaign_id, roster)
        alive = db.load_alive_roster(meta.campaign_id)
        assert len(alive) == 1
        assert alive[0].agent_id == "a"

    def test_roster_upsert(self, db):
        meta = db.create_campaign("Test")
        db.save_roster(meta.campaign_id, [RosterEntry(agent_id="a", name="A", xp=0)])
        db.save_roster(meta.campaign_id, [RosterEntry(agent_id="a", name="A", xp=100)])
        loaded = db.load_roster(meta.campaign_id)
        assert len(loaded) == 1
        assert loaded[0].xp == 100

    def test_roster_abilities_json(self, db):
        meta = db.create_campaign("Test")
        abilities = [{"name": "Fireball", "damage": 20, "mana_cost": 8}]
        db.save_roster(
            meta.campaign_id,
            [
                RosterEntry(agent_id="a", name="A", abilities=abilities),
            ],
        )
        loaded = db.load_roster(meta.campaign_id)
        assert loaded[0].abilities == abilities

    def test_roster_personality_json(self, db):
        meta = db.create_campaign("Test")
        db.save_roster(
            meta.campaign_id,
            [
                RosterEntry(
                    agent_id="a", name="A", personality_traits=["bold", "cunning"]
                ),
            ],
        )
        loaded = db.load_roster(meta.campaign_id)
        assert loaded[0].personality_traits == ["bold", "cunning"]

    # -- Battles --

    def test_save_load_battles(self, db):
        meta = db.create_campaign("Test")
        record = BattleRecord(
            battle_num=1,
            winner_ids=["a"],
            death_ids=["b"],
            rounds=12,
            xp_awards={"a": 175, "b": 30},
        )
        db.save_battle(meta.campaign_id, record)
        loaded = db.load_battles(meta.campaign_id)
        assert len(loaded) == 1
        assert loaded[0].winner_ids == ["a"]
        assert loaded[0].death_ids == ["b"]
        assert loaded[0].rounds == 12
        assert loaded[0].xp_awards == {"a": 175, "b": 30}

    # -- Memories --

    def test_save_load_memories(self, db):
        meta = db.create_campaign("Test")
        mems = [
            SerializedMemory(
                agent_id="a",
                description="saw enemy",
                poignancy=5,
                memory_type="observation",
                turn_created=1,
            ),
            SerializedMemory(
                agent_id="a",
                description="reflected on battle",
                poignancy=8,
                memory_type="reflection",
                turn_created=3,
            ),
        ]
        db.save_memories(meta.campaign_id, mems)
        loaded = db.load_memories(meta.campaign_id, "a")
        assert len(loaded) == 2
        assert {m.description for m in loaded} == {"saw enemy", "reflected on battle"}

    def test_memories_replace_per_agent(self, db):
        meta = db.create_campaign("Test")
        db.save_memories(
            meta.campaign_id,
            [
                SerializedMemory(
                    agent_id="a",
                    description="old",
                    poignancy=5,
                    memory_type="observation",
                    turn_created=0,
                ),
            ],
        )
        db.save_memories(
            meta.campaign_id,
            [
                SerializedMemory(
                    agent_id="a",
                    description="new",
                    poignancy=7,
                    memory_type="observation",
                    turn_created=1,
                ),
            ],
        )
        loaded = db.load_memories(meta.campaign_id, "a")
        assert len(loaded) == 1
        assert loaded[0].description == "new"

    # -- Relationships --

    def test_save_load_relationships(self, db):
        meta = db.create_campaign("Test")
        rels = [
            SerializedRelationship(
                owner_id="a",
                target_id="b",
                target_name="B",
                disposition=0.7,
                trust=0.9,
                betrayal_count=0,
                alliance_declared=True,
            ),
        ]
        db.save_relationships(meta.campaign_id, rels)
        loaded = db.load_relationships(meta.campaign_id, "a")
        assert len(loaded) == 1
        assert loaded[0].disposition == 0.7
        assert loaded[0].alliance_declared is True

    def test_relationships_replace_per_owner(self, db):
        meta = db.create_campaign("Test")
        db.save_relationships(
            meta.campaign_id,
            [
                SerializedRelationship(
                    owner_id="a",
                    target_id="b",
                    target_name="B",
                    disposition=0.5,
                    trust=0.5,
                    betrayal_count=0,
                    alliance_declared=False,
                ),
            ],
        )
        db.save_relationships(
            meta.campaign_id,
            [
                SerializedRelationship(
                    owner_id="a",
                    target_id="b",
                    target_name="B",
                    disposition=-0.8,
                    trust=0.1,
                    betrayal_count=1,
                    alliance_declared=False,
                ),
            ],
        )
        loaded = db.load_relationships(meta.campaign_id, "a")
        assert len(loaded) == 1
        assert loaded[0].disposition == -0.8
        assert loaded[0].betrayal_count == 1
