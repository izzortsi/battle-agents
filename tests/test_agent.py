"""Tests for the agent layer: Attributes, Identity, Agent, SocialModel."""

from __future__ import annotations

import pytest

from agent.attributes import Attributes
from agent.identity import Identity
from agent.agent import Agent
from agent.social_model import Relationship, SocialModel
from tests.conftest import make_agent


# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------


class TestAttributes:
    def test_defaults(self):
        a = Attributes()
        # max_hp = hp_base(40) + hp_per_con(8) * con(10) = 120
        assert a.hp == a.max_hp
        assert a.max_hp == 120
        # max_mana = mana_base(10) + mana_per_mgk(3) * mgk(10) = 40
        assert a.mana == a.max_mana
        assert a.max_mana == 40
        assert a.is_alive

    def test_take_damage(self):
        a = Attributes()
        actual = a.take_damage(30)
        assert actual == 30
        assert a.hp == a.max_hp - 30

    def test_take_damage_overkill(self):
        a = Attributes(hp=50)
        actual = a.take_damage(100)
        assert actual == 50  # actual damage capped at HP
        assert a.hp == 0
        assert not a.is_alive

    def test_take_damage_zero(self):
        a = Attributes()
        hp_before = a.hp
        actual = a.take_damage(0)
        assert actual == 0
        assert a.hp == hp_before

    def test_heal(self):
        a = Attributes(hp=50)
        actual = a.heal(30)
        assert actual == 30
        assert a.hp == 80

    def test_heal_capped_at_max(self):
        a = Attributes(hp=50)
        actual = a.heal(999)
        assert actual == a.max_hp - 50
        assert a.hp == a.max_hp

    def test_heal_at_full_hp(self):
        a = Attributes()  # hp starts at max
        actual = a.heal(20)
        assert actual == 0
        assert a.hp == a.max_hp

    def test_spend_mana_success(self):
        a = Attributes(mana=50)
        assert a.spend_mana(30)
        assert a.mana == 20

    def test_spend_mana_insufficient(self):
        a = Attributes(mana=10)
        assert not a.spend_mana(30)
        assert a.mana == 10  # unchanged

    def test_status_effects_tick(self):
        a = Attributes()
        a.status_effects = [
            {"type": "poison", "duration": 2, "magnitude": 5.0, "source": "trap"},
            {"type": "shield", "duration": 1, "magnitude": 0.5, "source": "mage"},
        ]
        expired = a.tick_status_effects()
        assert "shield" in expired
        assert "poison" not in expired
        assert len(a.status_effects) == 1
        assert a.status_effects[0]["type"] == "poison"

    def test_has_status(self):
        a = Attributes()
        a.status_effects = [
            {"type": "poison", "duration": 3, "magnitude": 5.0, "source": "trap"},
        ]
        assert a.has_status("poison")
        assert not a.has_status("shield")

    def test_effective_defense_with_defend(self):
        # phys_def = con(10) * 1.0 + atk(10) * 0.5 = 15
        a = Attributes(atk=10, con=10)
        base_def = a.phys_def  # 15
        a.status_effects = [
            {"type": "defend", "duration": 1, "magnitude": 0.5, "source": "self"},
        ]
        assert a.get_effective_defense() == int(base_def + base_def * 0.5)

    def test_effective_defense_no_bonus(self):
        a = Attributes(atk=10, con=10)
        assert a.get_effective_defense() == a.phys_def


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class TestIdentity:
    def test_defaults(self):
        i = Identity(name="Kael")
        assert i.name == "Kael"
        assert i.combat_class == "warrior"
        assert i.personality_traits == []

    def test_summary(self):
        i = Identity(name="Kael", combat_class="warrior", personality_traits=["brave"])
        s = i.summary
        assert "Kael" in s
        assert "warrior" in s
        assert "brave" in s

    def test_summary_no_traits(self):
        i = Identity(name="Kael")
        assert "unknown" in i.summary


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class TestAgent:
    def test_name_property(self):
        a = make_agent("kael", "Kael")
        assert a.name == "Kael"

    def test_is_alive(self):
        a = make_agent("kael", "Kael")
        assert a.is_alive
        a.attributes.hp = 0
        assert not a.is_alive

    def test_auto_social_model(self):
        a = make_agent("kael", "Kael")
        assert a.social is not None
        assert a.social.owner_id == "kael"

    def test_hashable(self):
        a = make_agent("kael", "Kael")
        b = make_agent("lyra", "Lyra")
        s = {a, b}
        assert len(s) == 2

    def test_equality_by_id(self):
        a = make_agent("kael", "Kael")
        b = make_agent("kael", "Different Name")
        assert a == b

    def test_status_summary(self):
        a = make_agent("kael", "Kael")
        a.attributes.hp = 75
        s = a.status_summary()
        assert "75" in s
        assert str(a.attributes.max_hp) in s


# ---------------------------------------------------------------------------
# SocialModel
# ---------------------------------------------------------------------------


class TestSocialModel:
    def test_ensure_relationship_creates(self):
        sm = SocialModel("kael")
        rel = sm.ensure_relationship("lyra", "Lyra")
        assert rel.agent_id == "lyra"
        assert rel.disposition == 0.0
        assert rel.trust == 0.5

    def test_ensure_relationship_idempotent(self):
        sm = SocialModel("kael")
        r1 = sm.ensure_relationship("lyra", "Lyra")
        r1.disposition = 0.5
        r2 = sm.ensure_relationship("lyra", "Lyra")
        assert r2.disposition == 0.5  # same object

    def test_get_relationship_missing(self):
        sm = SocialModel("kael")
        assert sm.get_relationship("nobody") is None

    def test_get_disposition_missing(self):
        sm = SocialModel("kael")
        assert sm.get_disposition("nobody") == 0.0

    def test_update_disposition_clamped(self):
        sm = SocialModel("kael")
        sm.ensure_relationship("lyra", "Lyra")
        result = sm.update_disposition("lyra", 5.0, "extreme", agent_name="Lyra")
        assert result == 1.0  # clamped

        result = sm.update_disposition("lyra", -10.0, "extreme negative", agent_name="Lyra")
        assert result == -1.0  # clamped

    def test_update_disposition_notes(self):
        sm = SocialModel("kael")
        sm.update_disposition("lyra", 0.3, "helped me", turn=5, agent_name="Lyra")
        rel = sm.get_relationship("lyra")
        assert len(rel.notes) == 1
        assert "helped me" in rel.notes[0]

    def test_update_trust_clamped(self):
        sm = SocialModel("kael")
        sm.ensure_relationship("lyra", "Lyra")
        result = sm.update_trust("lyra", 5.0, "Lyra")
        assert result == 1.0

        result = sm.update_trust("lyra", -10.0, "Lyra")
        assert result == 0.0

    def test_declare_alliance(self):
        sm = SocialModel("kael")
        sm.declare_alliance("lyra", turn=5, agent_name="Lyra")
        rel = sm.get_relationship("lyra")
        assert rel.alliance_declared
        assert rel.alliance_turn == 5

    def test_record_betrayal_clears_alliance(self):
        sm = SocialModel("kael")
        sm.declare_alliance("lyra", turn=5, agent_name="Lyra")
        sm.record_betrayal("lyra", turn=7, agent_name="Lyra")
        rel = sm.get_relationship("lyra")
        assert not rel.alliance_declared
        assert rel.betrayal_count == 1

    def test_get_allies(self):
        sm = SocialModel("kael")
        sm.update_disposition("lyra", 0.6, "friend", agent_name="Lyra")
        sm.update_disposition("vorn", 0.1, "neutral", agent_name="Vorn")
        allies = sm.get_allies(threshold=0.5)
        assert "lyra" in allies
        assert "vorn" not in allies

    def test_get_enemies(self):
        sm = SocialModel("kael")
        sm.update_disposition("lyra", -0.5, "foe", agent_name="Lyra")
        sm.update_disposition("vorn", 0.1, "neutral", agent_name="Vorn")
        enemies = sm.get_enemies(threshold=-0.3)
        assert "lyra" in enemies
        assert "vorn" not in enemies

    def test_on_attacked_by(self):
        sm = SocialModel("kael")
        sm.on_attacked_by("lyra", turn=3, damage=50, agent_name="Lyra")
        rel = sm.get_relationship("lyra")
        assert rel.disposition < 0
        assert rel.trust < 0.5

    def test_on_healed_by(self):
        sm = SocialModel("kael")
        sm.on_healed_by("lyra", turn=3, amount=30, agent_name="Lyra")
        rel = sm.get_relationship("lyra")
        assert rel.disposition > 0
        assert rel.trust > 0.5

    def test_on_ally_killed(self):
        sm = SocialModel("kael")
        sm.on_ally_killed("vorn", "lyra", turn=5, agent_name="Vorn")
        assert sm.get_disposition("vorn") < 0

    def test_on_enemy_killed(self):
        sm = SocialModel("kael")
        sm.on_enemy_killed("lyra", "vorn", turn=5, agent_name="Lyra")
        assert sm.get_disposition("lyra") > 0

    def test_on_attacked_ally_with_alliance(self):
        sm = SocialModel("kael")
        sm.declare_alliance("vorn", turn=1, agent_name="Vorn")
        sm.on_attacked_ally("vorn", "lyra", turn=5, agent_name="Vorn")
        rel = sm.get_relationship("vorn")
        assert not rel.alliance_declared  # alliance broken
        assert rel.betrayal_count == 1
        assert rel.disposition < -0.5

    def test_on_attacked_ally_without_alliance(self):
        sm = SocialModel("kael")
        sm.on_attacked_ally("vorn", "lyra", turn=5, agent_name="Vorn")
        assert sm.get_disposition("vorn") == pytest.approx(-0.15)

    def test_summary_no_relationships(self):
        sm = SocialModel("kael")
        assert "No relationships" in sm.summary()

    def test_summary_with_relationships(self):
        sm = SocialModel("kael")
        sm.update_disposition("lyra", 0.8, "best friend", agent_name="Lyra")
        s = sm.summary()
        assert "Lyra" in s
        assert "ally" in s
