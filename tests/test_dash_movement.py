"""Tests for movement (dash) effect on abilities — caster teleports near target."""

from __future__ import annotations

import pytest

from combat.actions import make_ability, make_move
from world.battle_grid import BattleGrid
from world.environment import Environment
from tests.conftest import make_agent


def _make_dash_ability(
    name: str = "Mirage Strike",
    damage: int = 22,
    ability_range: int = 3,
    mana_cost: int = 8,
) -> dict:
    """Create a dash ability with a movement effect."""
    return {
        "name": name,
        "mana_cost": mana_cost,
        "damage": damage,
        "range": ability_range,
        "aoe_pattern": "single",
        "cooldown": 3,
        "current_cd": 0,
        "effects": [
            {
                "type": "dust_step",
                "behavior": "stat_modifier",
                "duration": 1,
                "magnitude": 0.3,
                "target": "self",
                "category": "movement",
                "chance": 1.0,
            },
        ],
    }


def _env_with_two(ax: int, ay: int, bx: int, by: int, ability: dict):
    """Create an env with agent A (has ability) at (ax,ay) and agent B at (bx,by)."""
    grid = BattleGrid(width=10, height=10)
    env = Environment(grid=grid, perception_radius=12)

    # mgk=20 gives plenty of mana for ability costs
    a = make_agent("a", "A", attack_range=1, atk=15, mgk=20, con=10, hit=15)
    a.attributes.abilities = [ability]
    env.register_agent(a, ax, ay)

    b = make_agent("b", "B", attack_range=1, atk=10, con=20, hit=10)
    env.register_agent(b, bx, by)

    return env


class TestDashMovementEffect:
    def test_dash_teleports_caster_adjacent_to_target(self):
        """Using a dash ability should move the caster to a tile next to the target."""
        ability = _make_dash_ability(ability_range=4)
        env = _env_with_two(0, 0, 4, 0, ability)

        action = make_ability("a", "b", ability["name"])
        result = env.resolve_action(action)

        assert result.success
        assert "dashes to" in result.description

        # Caster should now be adjacent to target (4,0)
        new_pos = env.world_state.get_position("a")
        ax, ay = BattleGrid.parse_tile(new_pos)
        dist_to_target = BattleGrid.manhattan(ax, ay, 4, 0)
        assert dist_to_target == 1, (
            f"Expected adjacent (dist 1), got dist {dist_to_target} at ({ax},{ay})"
        )

    def test_dash_plus_free_move_in_same_turn(self):
        """Agent can use free move AND a dash ability — total movement > move_range."""
        ability = _make_dash_ability(ability_range=4)
        env = _env_with_two(0, 0, 7, 0, ability)

        # First: free move toward target (move_range=3)
        move_action = make_move("a", "3_0")
        move_result = env.resolve_action(move_action)
        assert move_result.success

        # Now at (3,0), target at (7,0) — distance 4, within ability range
        action = make_ability("a", "b", ability["name"])
        result = env.resolve_action(action)
        assert result.success
        assert "dashes to" in result.description

        # Caster should now be adjacent to target (7,0)
        new_pos = env.world_state.get_position("a")
        ax, ay = BattleGrid.parse_tile(new_pos)
        dist_to_target = BattleGrid.manhattan(ax, ay, 7, 0)
        assert dist_to_target == 1
        # Total movement from origin: started at (0,0), now near (7,0)
        total_move = BattleGrid.manhattan(0, 0, ax, ay)
        assert total_move > 3, (
            f"Should have moved more than move_range, moved {total_move}"
        )

    def test_dash_zero_damage_ability(self):
        """Dash ability with 0 damage (like Void Pounce) still teleports.

        Void Pounce has both enemy-targeting (disorient) and self-targeting
        (shadow_teleport) effects, plus 0 damage — so it is NOT self-targeting
        overall and still gets the offensive path with ability_target.
        """
        ability = {
            "name": "Void Pounce",
            "mana_cost": 7,
            "damage": 0,
            "range": 4,
            "aoe_pattern": "single",
            "cooldown": 4,
            "current_cd": 0,
            "effects": [
                {
                    "type": "disorient",
                    "behavior": "miss_chance",
                    "duration": 2,
                    "magnitude": 0.3,
                    "target": "enemy",
                    "category": "debuff",
                    "chance": 0.75,
                },
                {
                    "type": "shadow_teleport",
                    "behavior": "stat_modifier",
                    "duration": 1,
                    "magnitude": 0.0,
                    "target": "self",
                    "category": "movement",
                    "chance": 1.0,
                },
            ],
        }
        env = _env_with_two(0, 0, 4, 0, ability)

        action = make_ability("a", "b", ability["name"])
        result = env.resolve_action(action)

        assert result.success
        new_pos = env.world_state.get_position("a")
        ax, ay = BattleGrid.parse_tile(new_pos)
        dist_to_target = BattleGrid.manhattan(ax, ay, 4, 0)
        assert dist_to_target == 1

    def test_dash_adjacent_target_stays_put(self):
        """If already adjacent to target, dash should still work (no crash)."""
        ability = _make_dash_ability(ability_range=1)
        env = _env_with_two(3, 0, 4, 0, ability)

        action = make_ability("a", "b", ability["name"])
        result = env.resolve_action(action)
        assert result.success

    def test_dash_blocked_falls_back_to_caster_vicinity(self):
        """If all tiles adjacent to target are blocked, fall back to caster-adjacent."""
        ability = _make_dash_ability(ability_range=3)
        grid = BattleGrid(width=10, height=10)
        env = Environment(grid=grid, perception_radius=12)

        a = make_agent("a", "A", attack_range=1, atk=15, mgk=20, hit=15)
        a.attributes.abilities = [ability]
        env.register_agent(a, 0, 0)

        b = make_agent("b", "B", attack_range=1, con=20)
        env.register_agent(b, 3, 0)

        # Block all 4 tiles adjacent to target (3,0)
        for bx, by in [(2, 0), (4, 0), (3, 1)]:
            blocker = make_agent(f"block_{bx}_{by}", f"Block{bx}{by}", attack_range=1)
            env.register_agent(blocker, bx, by)
        # (3,-1) is out of bounds on a 10x10 grid — only 3 adjacent tiles

        action = make_ability("a", "b", ability["name"])
        result = env.resolve_action(action)
        assert result.success
        # Should still have dashed (to caster vicinity as fallback)
        assert "dashes to" in result.description

    def test_no_movement_effect_means_no_dash(self):
        """Ability without movement effect shouldn't move the caster."""
        ability = {
            "name": "Fireball",
            "mana_cost": 8,
            "damage": 25,
            "range": 3,
            "aoe_pattern": "single",
            "cooldown": 3,
            "current_cd": 0,
            "effects": [
                {
                    "type": "burn",
                    "behavior": "damage_over_time",
                    "duration": 2,
                    "magnitude": 0.05,
                    "target": "enemy",
                    "category": "debuff",
                    "chance": 0.8,
                },
            ],
        }
        env = _env_with_two(0, 0, 3, 0, ability)

        action = make_ability("a", "b", ability["name"])
        result = env.resolve_action(action)
        assert result.success

        # Caster should NOT have moved
        pos = env.world_state.get_position("a")
        assert pos == "0_0"
