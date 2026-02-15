"""Tests for the world layer: BattleGrid, TurnManager."""

from __future__ import annotations

import pytest

from world.battle_grid import BattleGrid, TileType
from world.turn_manager import TurnManager
from tests.conftest import make_agent


# ---------------------------------------------------------------------------
# BattleGrid
# ---------------------------------------------------------------------------


class TestBattleGrid:
    def test_dimensions(self, grid_5x5: BattleGrid):
        assert grid_5x5.width == 5
        assert grid_5x5.height == 5

    def test_all_tiles_floor_by_default(self, grid_5x5: BattleGrid):
        passable = list(grid_5x5.all_passable())
        assert len(passable) == 25

    def test_tile_key(self):
        assert BattleGrid.tile_key(3, 5) == "3_5"

    def test_parse_tile(self):
        assert BattleGrid.parse_tile("3_5") == (3, 5)

    def test_manhattan_distance(self):
        assert BattleGrid.manhattan(0, 0, 3, 4) == 7

    def test_tile_distance(self):
        assert BattleGrid.tile_distance("0_0", "3_4") == 7

    def test_in_bounds(self, grid_5x5: BattleGrid):
        assert grid_5x5.in_bounds(0, 0)
        assert grid_5x5.in_bounds(4, 4)
        assert not grid_5x5.in_bounds(-1, 0)
        assert not grid_5x5.in_bounds(5, 0)
        assert not grid_5x5.in_bounds(0, 5)

    def test_is_passable(self, grid_5x5: BattleGrid):
        assert grid_5x5.is_passable(2, 2)
        assert not grid_5x5.is_passable(-1, 0)

    def test_set_wall(self, grid_5x5: BattleGrid):
        grid_5x5.set_wall(2, 2)
        assert not grid_5x5.is_passable(2, 2)

    def test_set_wall_out_of_bounds_noop(self, grid_5x5: BattleGrid):
        grid_5x5.set_wall(99, 99)  # should not raise

    def test_adjacent_tiles(self, grid_5x5: BattleGrid):
        adj = grid_5x5.adjacent_tiles(2, 2)
        assert set(adj) == {(1, 2), (3, 2), (2, 1), (2, 3)}

    def test_adjacent_tiles_corner(self, grid_5x5: BattleGrid):
        adj = grid_5x5.adjacent_tiles(0, 0)
        assert set(adj) == {(1, 0), (0, 1)}

    def test_adjacent_tiles_wall_blocked(self, grid_5x5: BattleGrid):
        grid_5x5.set_wall(3, 2)
        adj = grid_5x5.adjacent_tiles(2, 2)
        assert (3, 2) not in adj

    def test_tiles_in_range(self, grid_5x5: BattleGrid):
        tiles = grid_5x5.tiles_in_range(2, 2, 1)
        # Center + 4 adjacent
        assert len(tiles) == 5
        assert (2, 2) in tiles

    def test_tiles_in_range_excludes_walls(self, grid_5x5: BattleGrid):
        grid_5x5.set_wall(3, 2)
        tiles = grid_5x5.tiles_in_range(2, 2, 1)
        assert (3, 2) not in tiles

    def test_tiles_in_radius_includes_walls(self, grid_5x5: BattleGrid):
        grid_5x5.set_wall(3, 2)
        tiles = grid_5x5.tiles_in_radius(2, 2, 1)
        assert (3, 2) in tiles  # radius includes all in-bounds tiles

    def test_tiles_in_radius_respects_bounds(self, grid_5x5: BattleGrid):
        tiles = grid_5x5.tiles_in_radius(0, 0, 2)
        for x, y in tiles:
            assert grid_5x5.in_bounds(x, y)

    # --- New tile types (STONE, PILLAR, GRAVEL, CRACKED, RUNE) ---

    def test_stone_is_passable(self):
        grid = BattleGrid(width=5, height=5)
        grid._tiles[(2, 2)] = TileType.STONE
        assert grid.is_passable(2, 2)

    def test_gravel_is_passable(self):
        grid = BattleGrid(width=5, height=5)
        grid._tiles[(2, 2)] = TileType.GRAVEL
        assert grid.is_passable(2, 2)

    def test_cracked_is_passable(self):
        grid = BattleGrid(width=5, height=5)
        grid._tiles[(2, 2)] = TileType.CRACKED
        assert grid.is_passable(2, 2)

    def test_rune_is_passable(self):
        grid = BattleGrid(width=5, height=5)
        grid._tiles[(2, 2)] = TileType.RUNE
        assert grid.is_passable(2, 2)

    def test_pillar_is_impassable(self):
        grid = BattleGrid(width=5, height=5)
        grid._tiles[(2, 2)] = TileType.PILLAR
        assert not grid.is_passable(2, 2)

    def test_pillar_blocked_in_adjacent(self):
        grid = BattleGrid(width=5, height=5)
        grid._tiles[(3, 2)] = TileType.PILLAR
        adj = grid.adjacent_tiles(2, 2)
        assert (3, 2) not in adj

    def test_pillar_excluded_from_tiles_in_range(self):
        grid = BattleGrid(width=5, height=5)
        grid._tiles[(3, 2)] = TileType.PILLAR
        tiles = grid.tiles_in_range(2, 2, 1)
        assert (3, 2) not in tiles

    def test_pillar_included_in_tiles_in_radius(self):
        grid = BattleGrid(width=5, height=5)
        grid._tiles[(3, 2)] = TileType.PILLAR
        tiles = grid.tiles_in_radius(2, 2, 1)
        assert (3, 2) in tiles

    def test_stone_in_all_passable(self):
        grid = BattleGrid(width=3, height=3)
        grid._tiles[(1, 1)] = TileType.STONE
        passable = list(grid.all_passable())
        assert (1, 1) in passable

    def test_pillar_not_in_all_passable(self):
        grid = BattleGrid(width=3, height=3)
        grid._tiles[(1, 1)] = TileType.PILLAR
        passable = list(grid.all_passable())
        assert (1, 1) not in passable

    def test_tile_char_stone(self):
        grid = BattleGrid(width=3, height=3)
        grid._tiles[(1, 1)] = TileType.STONE
        assert grid.tile_char(1, 1) == "s"

    def test_tile_char_pillar(self):
        grid = BattleGrid(width=3, height=3)
        grid._tiles[(1, 1)] = TileType.PILLAR
        assert grid.tile_char(1, 1) == "O"

    def test_tile_char_gravel(self):
        grid = BattleGrid(width=3, height=3)
        grid._tiles[(1, 1)] = TileType.GRAVEL
        assert grid.tile_char(1, 1) == ","

    def test_tile_char_cracked(self):
        grid = BattleGrid(width=3, height=3)
        grid._tiles[(1, 1)] = TileType.CRACKED
        assert grid.tile_char(1, 1) == "x"

    def test_tile_char_rune(self):
        grid = BattleGrid(width=3, height=3)
        grid._tiles[(1, 1)] = TileType.RUNE
        assert grid.tile_char(1, 1) == "*"

    def test_gravel_in_all_passable(self):
        grid = BattleGrid(width=3, height=3)
        grid._tiles[(1, 1)] = TileType.GRAVEL
        assert (1, 1) in list(grid.all_passable())

    def test_cracked_in_all_passable(self):
        grid = BattleGrid(width=3, height=3)
        grid._tiles[(1, 1)] = TileType.CRACKED
        assert (1, 1) in list(grid.all_passable())

    def test_rune_in_all_passable(self):
        grid = BattleGrid(width=3, height=3)
        grid._tiles[(1, 1)] = TileType.RUNE
        assert (1, 1) in list(grid.all_passable())

    # --- Arena layout ---

    def test_create_arena_dimensions(self):
        arena = BattleGrid.create_arena()
        assert arena.width == 12
        assert arena.height == 10

    def test_create_arena_has_pillars(self):
        arena = BattleGrid.create_arena()
        pillar_tiles = [
            (x, y)
            for x in range(arena.width)
            for y in range(arena.height)
            if arena.get_tile(x, y) == TileType.PILLAR
        ]
        assert len(pillar_tiles) == 4

    def test_create_arena_pillars_are_symmetric(self):
        arena = BattleGrid.create_arena()
        pillars = {
            (x, y)
            for x in range(arena.width)
            for y in range(arena.height)
            if arena.get_tile(x, y) == TileType.PILLAR
        }
        cx = (arena.width - 1) / 2
        cy = (arena.height - 1) / 2
        for px, py in pillars:
            mirror_x = int(2 * cx - px)
            mirror_y = int(2 * cy - py)
            assert (mirror_x, py) in pillars, (
                f"Missing horizontal mirror of pillar ({px},{py})"
            )
            assert (px, mirror_y) in pillars, (
                f"Missing vertical mirror of pillar ({px},{py})"
            )

    def test_create_arena_has_stone_tiles(self):
        arena = BattleGrid.create_arena()
        stone_count = sum(
            1
            for x in range(arena.width)
            for y in range(arena.height)
            if arena.get_tile(x, y) == TileType.STONE
        )
        assert stone_count > 0

    def test_create_arena_mostly_passable(self):
        arena = BattleGrid.create_arena()
        total = arena.width * arena.height
        passable = len(list(arena.all_passable()))
        ratio = passable / total
        assert ratio >= 0.90, f"Arena is only {ratio:.0%} passable, expected >= 90%"

    def test_create_arena_serialize_includes_new_types(self):
        arena = BattleGrid.create_arena()
        serialized = arena.serialize_tiles()
        all_types = {
            serialized[y][x] for x in range(arena.width) for y in range(arena.height)
        }
        assert "stone" in all_types
        assert "pillar" in all_types
        assert "floor" in all_types
        assert "gravel" in all_types
        assert "cracked" in all_types
        assert "rune" in all_types

    def test_create_arena_has_gravel_tiles(self):
        arena = BattleGrid.create_arena()
        gravel_count = sum(
            1
            for x in range(arena.width)
            for y in range(arena.height)
            if arena.get_tile(x, y) == TileType.GRAVEL
        )
        assert gravel_count > 0

    def test_create_arena_has_cracked_tiles(self):
        arena = BattleGrid.create_arena()
        cracked_count = sum(
            1
            for x in range(arena.width)
            for y in range(arena.height)
            if arena.get_tile(x, y) == TileType.CRACKED
        )
        assert cracked_count > 0

    def test_create_arena_has_rune_tiles(self):
        arena = BattleGrid.create_arena()
        rune_count = sum(
            1
            for x in range(arena.width)
            for y in range(arena.height)
            if arena.get_tile(x, y) == TileType.RUNE
        )
        assert rune_count > 0

    def test_create_arena_custom_dimensions(self):
        arena = BattleGrid.create_arena(width=8, height=6)
        assert arena.width == 8
        assert arena.height == 6
        # Should still have pillars
        pillar_tiles = [
            (x, y)
            for x in range(arena.width)
            for y in range(arena.height)
            if arena.get_tile(x, y) == TileType.PILLAR
        ]
        assert len(pillar_tiles) == 4


# ---------------------------------------------------------------------------
# TurnManager
# ---------------------------------------------------------------------------


class TestTurnManager:
    def test_roll_initiative_orders_by_speed(self):
        tm = TurnManager()
        fast = make_agent("fast", "Fast", speed=20)
        slow = make_agent("slow", "Slow", speed=5)
        mid = make_agent("mid", "Mid", speed=10)
        order = tm.roll_initiative([fast, slow, mid])
        assert order[0] == "fast"
        assert order[-1] == "slow"

    def test_roll_initiative_sets_round_1(self):
        tm = TurnManager()
        agents = [make_agent("a", "A"), make_agent("b", "B")]
        tm.roll_initiative(agents)
        assert tm.round_number == 1

    def test_current_agent(self):
        tm = TurnManager()
        agents = [make_agent("a", "A", speed=20), make_agent("b", "B", speed=10)]
        tm.roll_initiative(agents)
        assert tm.current_agent_id == "a"

    def test_current_agent_no_order(self):
        tm = TurnManager()
        assert tm.current_agent_id is None

    def test_advance(self):
        tm = TurnManager()
        agents = [make_agent("a", "A", speed=20), make_agent("b", "B", speed=10)]
        tm.roll_initiative(agents)
        assert tm.current_agent_id == "a"
        next_id = tm.advance()
        assert next_id == "b"

    def test_advance_wraps_round(self):
        tm = TurnManager()
        agents = [make_agent("a", "A", speed=20), make_agent("b", "B", speed=10)]
        tm.roll_initiative(agents)
        assert tm.round_number == 1
        tm.advance()  # b
        tm.advance()  # wrap to a, round 2
        assert tm.round_number == 2
        assert tm.current_agent_id == "a"

    def test_remove_agent(self):
        tm = TurnManager()
        agents = [
            make_agent("a", "A", speed=20),
            make_agent("b", "B", speed=15),
            make_agent("c", "C", speed=10),
        ]
        tm.roll_initiative(agents)
        tm.remove_agent("b")
        assert "b" not in tm.turn_order

    def test_remove_current_agent(self):
        tm = TurnManager()
        agents = [
            make_agent("a", "A", speed=20),
            make_agent("b", "B", speed=15),
            make_agent("c", "C", speed=10),
        ]
        tm.roll_initiative(agents)
        # Current is "a", remove it
        tm.remove_agent("a")
        assert "a" not in tm.turn_order
        # Should advance to next valid agent
        assert tm.current_agent_id in {"b", "c"}

    def test_turn_order_is_copy(self):
        tm = TurnManager()
        agents = [make_agent("a", "A"), make_agent("b", "B")]
        tm.roll_initiative(agents)
        order = tm.turn_order
        order.append("intruder")
        assert "intruder" not in tm.turn_order

    def test_global_turn(self):
        tm = TurnManager()
        agents = [make_agent("a", "A", speed=20), make_agent("b", "B", speed=10)]
        tm.roll_initiative(agents)
        # Round 1, first agent
        t1 = tm.global_turn
        tm.advance()
        t2 = tm.global_turn
        assert t2 > t1
