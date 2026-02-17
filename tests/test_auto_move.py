"""Tests for find_auto_move_tile — auto-move toward target on range failure."""

from __future__ import annotations

import pytest

from combat.action_resolver import find_auto_move_tile
from world.battle_grid import BattleGrid
from world.environment import Environment
from tests.conftest import make_agent


def _env_with_agents(width=10, height=10, agents=None):
    """Create an Environment with agents placed at given positions.

    agents: list of (agent_id, name, x, y, attack_range) tuples.
    """
    grid = BattleGrid(width=width, height=height)
    env = Environment(grid=grid, perception_radius=12)
    for aid, name, x, y, ar in agents or []:
        a = make_agent(aid, name, attack_range=ar)
        env.register_agent(a, x, y)
    return env


class TestFindAutoMoveTile:
    def test_already_in_range_returns_none(self):
        """If already within required range, no move needed."""
        env = _env_with_agents(
            agents=[
                ("a", "A", 3, 3, 1),
                ("b", "B", 3, 4, 1),
            ]
        )
        result = find_auto_move_tile("a", "b", 1, env)
        assert result is None

    def test_moves_toward_target_melee(self):
        """Agent at (0,0), target at (5,5), melee range 1, move_range 3.
        Should pick a tile within 3 of (0,0) that is closest to (5,5)."""
        env = _env_with_agents(
            agents=[
                ("a", "A", 0, 0, 1),
                ("b", "B", 5, 5, 1),
            ]
        )
        tile = find_auto_move_tile("a", "b", 1, env)
        assert tile is not None
        x, y = BattleGrid.parse_tile(tile)
        # Should be within move_range of origin (0,0)
        assert BattleGrid.manhattan(0, 0, x, y) <= 3
        # Should be closer to target than we started
        assert BattleGrid.manhattan(x, y, 5, 5) < BattleGrid.manhattan(0, 0, 5, 5)

    def test_moves_into_range_when_possible(self):
        """Agent at (0,0), target at (3,0), attack range 1, move_range 3.
        Can reach range 1 of target: tile (2,0) is distance 2 from origin
        and distance 1 from target."""
        env = _env_with_agents(
            agents=[
                ("a", "A", 0, 0, 1),
                ("b", "B", 3, 0, 1),
            ]
        )
        tile = find_auto_move_tile("a", "b", 1, env)
        assert tile is not None
        x, y = BattleGrid.parse_tile(tile)
        dist_to_target = BattleGrid.manhattan(x, y, 3, 0)
        assert dist_to_target <= 1  # now within attack range

    def test_ranged_ability_uses_correct_range(self):
        """With required_range=3, agent at (0,0), target at (5,0).
        Should move to (2,0) which puts target at distance 3."""
        env = _env_with_agents(
            agents=[
                ("a", "A", 0, 0, 1),
                ("b", "B", 5, 0, 1),
            ]
        )
        tile = find_auto_move_tile("a", "b", 3, env)
        assert tile is not None
        x, y = BattleGrid.parse_tile(tile)
        dist_to_target = BattleGrid.manhattan(x, y, 5, 0)
        assert dist_to_target <= 3  # now within ability range

    def test_avoids_occupied_tiles(self):
        """Auto-move should not pick tiles occupied by other living agents."""
        env = _env_with_agents(
            agents=[
                ("a", "A", 0, 0, 1),
                ("b", "B", 4, 0, 1),
                ("c", "C", 2, 0, 1),  # blocker on the direct path
            ]
        )
        tile = find_auto_move_tile("a", "b", 1, env)
        assert tile is not None
        x, y = BattleGrid.parse_tile(tile)
        # Should not be the blocker's position
        assert (x, y) != (2, 0)

    def test_avoids_walls(self):
        """Auto-move should not pick impassable tiles."""
        grid = BattleGrid(width=10, height=10)
        # Wall off the direct path
        grid.set_wall(1, 0)
        grid.set_wall(2, 0)
        env = Environment(grid=grid, perception_radius=12)
        a = make_agent("a", "A", attack_range=1)
        b = make_agent("b", "B", attack_range=1)
        env.register_agent(a, 0, 0)
        env.register_agent(b, 4, 0)

        tile = find_auto_move_tile("a", "b", 1, env)
        assert tile is not None
        x, y = BattleGrid.parse_tile(tile)
        # Should not be on a wall
        assert (x, y) != (1, 0)
        assert (x, y) != (2, 0)

    def test_no_valid_tile_returns_none(self):
        """If completely surrounded by walls within move range, return None."""
        grid = BattleGrid(width=10, height=10)
        # Wall off every tile within move_range=3 of (5,5) except (5,5) itself
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if abs(dx) + abs(dy) > 3:
                    continue
                if dx == 0 and dy == 0:
                    continue
                grid.set_wall(5 + dx, 5 + dy)
        env = Environment(grid=grid, perception_radius=12)
        a = make_agent("a", "A", attack_range=1)
        b = make_agent("b", "B", attack_range=1)
        env.register_agent(a, 5, 5)
        env.register_agent(b, 9, 9)

        tile = find_auto_move_tile("a", "b", 1, env)
        assert tile is None

    def test_nonexistent_agent_returns_none(self):
        """If either agent doesn't exist, return None."""
        env = _env_with_agents(
            agents=[
                ("a", "A", 0, 0, 1),
            ]
        )
        assert find_auto_move_tile("a", "missing", 1, env) is None
        assert find_auto_move_tile("missing", "a", 1, env) is None

    def test_prefers_in_range_tile_over_closer_out_of_range(self):
        """Given a choice between a tile that puts us in range vs one that
        is slightly closer to target but still out of range, prefer in-range."""
        env = _env_with_agents(
            agents=[
                ("a", "A", 0, 0, 1),
                ("b", "B", 4, 0, 1),
            ]
        )
        tile = find_auto_move_tile("a", "b", 1, env)
        assert tile is not None
        x, y = BattleGrid.parse_tile(tile)
        # move_range=3, target at (4,0), so (3,0) is reachable and in range 1
        assert BattleGrid.manhattan(x, y, 4, 0) <= 1
