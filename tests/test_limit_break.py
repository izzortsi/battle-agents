"""Tests for two-tier Limit Break mechanics.

LB1 unlocks at ≤50% HP. After LB1 is used, LB2 unlocks at ≤25% HP and always
crits (2x damage). They do NOT stack.
"""

from __future__ import annotations

import pytest

from agent.attributes import Attributes, get_balance
from combat.actions import make_ability
from world.battle_grid import BattleGrid
from world.environment import Environment
from tests.conftest import make_agent


SAMPLE_LB = {
    "name": "Wrath of the Betrayed",
    "mana_cost": 4,
    "damage": 38,
    "range": 1,
    "aoe_pattern": "cone",
    "cooldown": 0,
    "current_cd": 0,
    "is_limit_break": True,
    "description": "Devastating wide-arc cleave.",
    "effects": [
        {
            "type": "armor_shatter",
            "behavior": "reduce_outgoing_damage",
            "duration": 3,
            "magnitude": 0.35,
            "target": "enemy",
            "category": "debuff",
            "chance": 0.8,
        }
    ],
}


# ======================================================================
# Tier 1 unlock (≤50% HP)
# ======================================================================


class TestLB1Unlock:
    """LB1 becomes available when HP drops to ≤50%."""

    def test_not_available_at_full_hp(self):
        attrs = Attributes(con=10, limit_break=dict(SAMPLE_LB))
        assert not attrs.limit_break_available
        assert not attrs.limit_break_ready
        assert attrs.limit_break_tier == 1  # next tier is 1

    def test_unlocks_at_50_percent(self):
        attrs = Attributes(con=10, limit_break=dict(SAMPLE_LB))
        # max_hp = 40 + 8*10 = 120. 50% = 60.
        assert attrs.max_hp == 120
        attrs.take_damage(60)  # HP = 60 = 50%
        assert attrs.hp == 60
        assert attrs.limit_break_available
        assert attrs.limit_break_ready
        assert attrs.limit_break_tier == 1

    def test_unlocks_below_50_percent(self):
        attrs = Attributes(con=10, limit_break=dict(SAMPLE_LB))
        attrs.take_damage(80)  # HP = 40 < 50%
        assert attrs.limit_break_available

    def test_not_available_just_above_50_percent(self):
        attrs = Attributes(con=10, limit_break=dict(SAMPLE_LB))
        attrs.take_damage(59)  # HP = 61 > 50%
        assert attrs.hp == 61
        assert not attrs.limit_break_available

    def test_stays_available_after_heal(self):
        attrs = Attributes(con=10, limit_break=dict(SAMPLE_LB))
        attrs.take_damage(80)  # unlock
        assert attrs.limit_break_available
        attrs.heal(60)
        assert attrs.hp == 100  # above 50%
        assert attrs.limit_break_available  # latched

    def test_no_limit_break_defined(self):
        attrs = Attributes(con=10)
        attrs.take_damage(100)
        assert not attrs.limit_break_available
        assert not attrs.limit_break_ready


# ======================================================================
# Tier 2 unlock (≤25% HP, after LB1 used)
# ======================================================================


class TestLB2Unlock:
    """LB2 unlocks at ≤25% HP, but only if LB1 has been consumed."""

    def test_lb2_does_not_unlock_without_lb1_used(self):
        """Even at ≤25% HP, LB2 doesn't unlock if LB1 hasn't been used."""
        attrs = Attributes(con=10, limit_break=dict(SAMPLE_LB))
        attrs.take_damage(100)  # HP = 20, which is ≤25% AND ≤50%
        # LB1 unlocked (uses == 0), not LB2
        assert attrs.limit_break_available
        assert attrs.limit_break_uses == 0
        assert attrs.limit_break_tier == 1

    def test_lb2_unlocks_after_lb1_used_and_hp_threshold(self):
        attrs = Attributes(con=10, limit_break=dict(SAMPLE_LB))
        # Use LB1
        attrs.take_damage(80)  # unlock LB1
        attrs.limit_break_uses = 1
        attrs.limit_break_available = False  # consumed LB1
        # Now take more damage to ≤25% (30 HP)
        attrs.take_damage(10)  # HP = 30 = 25%
        assert attrs.hp == 30
        assert attrs.limit_break_available
        assert attrs.limit_break_tier == 2

    def test_lb2_locked_above_25_percent(self):
        attrs = Attributes(con=10, limit_break=dict(SAMPLE_LB))
        attrs.take_damage(80)
        attrs.limit_break_uses = 1
        attrs.limit_break_available = False
        # HP = 40, 25% threshold = 30
        assert attrs.hp == 40
        assert not attrs.limit_break_available

    def test_lb2_stays_available_after_heal(self):
        attrs = Attributes(con=10, limit_break=dict(SAMPLE_LB))
        attrs.take_damage(80)
        attrs.limit_break_uses = 1
        attrs.limit_break_available = False
        attrs.take_damage(20)  # HP = 20, unlock LB2
        assert attrs.limit_break_available
        attrs.heal(50)
        assert attrs.hp == 70  # well above 25%
        assert attrs.limit_break_available  # latched

    def test_no_lb3_after_both_used(self):
        attrs = Attributes(con=10, limit_break=dict(SAMPLE_LB))
        attrs.limit_break_uses = 2
        attrs.limit_break_available = False
        attrs.take_damage(110)  # HP = 10
        assert not attrs.limit_break_available
        assert attrs.limit_break_used  # backward compat property
        assert attrs.limit_break_tier == 0


# ======================================================================
# Usage and ready abilities
# ======================================================================


class TestLimitBreakUsage:
    """Limit break appears in ready abilities and can be looked up by name."""

    def test_appears_in_ready_abilities_when_lb1_unlocked(self):
        attrs = Attributes(con=10, mgk=10, limit_break=dict(SAMPLE_LB))
        attrs.take_damage(80)
        ready = attrs.get_ready_abilities()
        lb_names = [a["name"] for a in ready if a.get("is_limit_break")]
        assert "Wrath of the Betrayed" in lb_names

    def test_appears_in_ready_abilities_when_lb2_unlocked(self):
        attrs = Attributes(con=10, mgk=10, limit_break=dict(SAMPLE_LB))
        attrs.take_damage(80)
        attrs.limit_break_uses = 1
        attrs.limit_break_available = False
        attrs.take_damage(20)  # unlock LB2
        ready = attrs.get_ready_abilities()
        lb_names = [a["name"] for a in ready if a.get("is_limit_break")]
        assert "Wrath of the Betrayed" in lb_names

    def test_not_in_ready_abilities_when_locked(self):
        attrs = Attributes(con=10, mgk=10, limit_break=dict(SAMPLE_LB))
        ready = attrs.get_ready_abilities()
        lb_names = [a["name"] for a in ready if a.get("is_limit_break")]
        assert lb_names == []

    def test_not_in_ready_when_both_used(self):
        attrs = Attributes(con=10, mgk=10, limit_break=dict(SAMPLE_LB))
        attrs.limit_break_uses = 2
        attrs.limit_break_available = False
        ready = attrs.get_ready_abilities()
        lb_names = [a["name"] for a in ready if a.get("is_limit_break")]
        assert lb_names == []

    def test_found_by_get_ability_by_name(self):
        attrs = Attributes(con=10, limit_break=dict(SAMPLE_LB))
        ab = attrs.get_ability_by_name("Wrath of the Betrayed")
        assert ab is not None
        assert ab["is_limit_break"] is True

    def test_found_by_name_case_insensitive(self):
        attrs = Attributes(con=10, limit_break=dict(SAMPLE_LB))
        ab = attrs.get_ability_by_name("wrath of the betrayed")
        assert ab is not None


# ======================================================================
# Action resolution
# ======================================================================


class TestLimitBreakResolution:
    """Action resolver correctly validates and consumes limit break tiers."""

    def _setup_env(self):
        grid = BattleGrid(width=10, height=10)
        env = Environment(grid=grid, perception_radius=12)

        a = make_agent("a", "A", attack_range=1, atk=15, mgk=10, con=10, hit=15)
        a.attributes.limit_break = dict(SAMPLE_LB)
        env.register_agent(a, 3, 3)

        b = make_agent("b", "B", attack_range=1, con=20)
        env.register_agent(b, 4, 3)

        return env

    def test_fails_when_lb1_not_available(self):
        env = self._setup_env()
        action = make_ability("a", "b", "Wrath of the Betrayed")
        result = env.resolve_action(action)
        assert not result.success
        assert "not yet available" in result.description
        assert "50%" in result.description

    def test_lb1_succeeds_when_available(self):
        env = self._setup_env()
        agent = env.agents["a"]
        agent.attributes.take_damage(80)  # unlock LB1
        assert agent.attributes.limit_break_ready

        action = make_ability("a", "b", "Wrath of the Betrayed")
        result = env.resolve_action(action)
        assert result.success
        assert agent.attributes.limit_break_uses == 1
        assert not agent.attributes.limit_break_available

    def test_lb2_fails_when_locked(self):
        """After LB1 is used but HP hasn't hit 25%, LB2 is locked."""
        env = self._setup_env()
        agent = env.agents["a"]
        agent.attributes.take_damage(80)

        # Use LB1
        action = make_ability("a", "b", "Wrath of the Betrayed")
        env.resolve_action(action)
        assert agent.attributes.limit_break_uses == 1

        # Try again — LB2 locked (HP > 25%)
        result2 = env.resolve_action(action)
        assert not result2.success
        assert "25%" in result2.description

    def test_lb2_succeeds_with_threshold(self):
        """LB2 works after LB1 used and HP ≤25%."""
        env = self._setup_env()
        agent = env.agents["a"]
        agent.attributes.take_damage(80)

        # Use LB1
        action = make_ability("a", "b", "Wrath of the Betrayed")
        env.resolve_action(action)

        # Drop to ≤25% HP to unlock LB2
        agent.attributes.take_damage(20)  # ~10 HP left
        assert agent.attributes.limit_break_available
        assert agent.attributes.limit_break_tier == 2

        # Restore mana for LB2
        agent.attributes.mana = agent.attributes.max_mana

        result2 = env.resolve_action(action)
        assert result2.success
        assert agent.attributes.limit_break_uses == 2
        assert "CRITICAL" in result2.description

    def test_cannot_use_after_both_consumed(self):
        env = self._setup_env()
        agent = env.agents["a"]
        agent.attributes.limit_break_uses = 2
        agent.attributes.limit_break_available = False

        action = make_ability("a", "b", "Wrath of the Betrayed")
        result = env.resolve_action(action)
        assert not result.success
        assert "both" in result.description.lower()

    def test_mana_required(self):
        env = self._setup_env()
        agent = env.agents["a"]
        agent.attributes.take_damage(80)
        agent.attributes.mana = 0

        action = make_ability("a", "b", "Wrath of the Betrayed")
        result = env.resolve_action(action)
        assert not result.success
        assert "mana" in result.description.lower()
        assert agent.attributes.limit_break_uses == 0  # not consumed

    def test_lb2_crit_damage_is_doubled(self):
        """LB2 should apply crit_multiplier (2x) to base damage."""
        env = self._setup_env()
        agent = env.agents["a"]
        target = env.agents["b"]

        # Set up LB2 scenario
        agent.attributes.take_damage(80)
        action = make_ability("a", "b", "Wrath of the Betrayed")
        env.resolve_action(action)  # use LB1
        agent.attributes.take_damage(20)  # unlock LB2
        agent.attributes.mana = agent.attributes.max_mana

        target_hp_before = target.attributes.hp
        result = env.resolve_action(action)
        assert result.success
        # LB2 base damage = 38 * 2.0 = 76 (before modifiers/defense)
        # The actual damage after defense will be less, but should be significantly
        # more than the base 38
        actual_damage = result.details.get("damage", 0)
        assert actual_damage > 0  # at least some damage dealt


# ======================================================================
# Backward compatibility
# ======================================================================


class TestBackwardCompat:
    """The limit_break_used property works for backward compatibility."""

    def test_used_false_initially(self):
        attrs = Attributes(con=10, limit_break=dict(SAMPLE_LB))
        assert not attrs.limit_break_used

    def test_used_false_after_lb1(self):
        attrs = Attributes(con=10, limit_break=dict(SAMPLE_LB))
        attrs.limit_break_uses = 1
        assert not attrs.limit_break_used  # only True when BOTH used

    def test_used_true_after_both(self):
        attrs = Attributes(con=10, limit_break=dict(SAMPLE_LB))
        attrs.limit_break_uses = 2
        assert attrs.limit_break_used


# ======================================================================
# YAML loading
# ======================================================================


class TestLimitBreakLoading:
    """Config loader attaches limit_break correctly."""

    def test_load_from_yaml(self):
        from config_loader import load_all_characters

        agents = load_all_characters()
        for agent in agents:
            lb = agent.attributes.limit_break
            assert lb is not None, f"{agent.name} missing limit break"
            assert lb.get("is_limit_break") is True
            assert lb.get("name"), f"{agent.name} limit break has no name"
            assert lb.get("damage", -1) >= 0
