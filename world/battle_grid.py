"""N×M tile grid with collision detection and distance calculation.

Tiles are identified by string keys "x_y" (e.g. "3_5").
Supports passability checks and adjacent-tile movement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator


class TileType(str, Enum):
    FLOOR = "floor"
    WALL = "wall"
    FURNITURE = "furniture"  # impassable décor (tables, bar counters)
    DOOR = "door"  # passable entry/exit point


@dataclass
class BattleGrid:
    width: int
    height: int
    _tiles: dict[tuple[int, int], TileType] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        # Default all tiles to floor
        if not self._tiles:
            for x in range(self.width):
                for y in range(self.height):
                    self._tiles[(x, y)] = TileType.FLOOR

    # -- Tile helpers ----------------------------------------------------------

    @staticmethod
    def tile_key(x: int, y: int) -> str:
        return f"{x}_{y}"

    @staticmethod
    def parse_tile(tile: str) -> tuple[int, int]:
        parts = tile.split("_")
        return int(parts[0]), int(parts[1])

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_passable(self, x: int, y: int) -> bool:
        t = self._tiles.get((x, y))
        return self.in_bounds(x, y) and t not in (TileType.WALL, TileType.FURNITURE)

    def set_wall(self, x: int, y: int) -> None:
        if self.in_bounds(x, y):
            self._tiles[(x, y)] = TileType.WALL

    # -- Distance --------------------------------------------------------------

    @staticmethod
    def manhattan(ax: int, ay: int, bx: int, by: int) -> int:
        return abs(ax - bx) + abs(ay - by)

    @classmethod
    def tile_distance(cls, tile_a: str, tile_b: str) -> int:
        ax, ay = cls.parse_tile(tile_a)
        bx, by = cls.parse_tile(tile_b)
        return cls.manhattan(ax, ay, bx, by)

    # -- Adjacency / movement --------------------------------------------------

    def adjacent_tiles(self, x: int, y: int) -> list[tuple[int, int]]:
        """Return passable tiles adjacent to (x, y) — 4-directional."""
        candidates = [(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)]
        return [(cx, cy) for cx, cy in candidates if self.is_passable(cx, cy)]

    def tiles_in_range(self, x: int, y: int, max_range: int) -> list[tuple[int, int]]:
        """All passable tiles within Manhattan distance `max_range`."""
        result: list[tuple[int, int]] = []
        for dx in range(-max_range, max_range + 1):
            for dy in range(-max_range, max_range + 1):
                if abs(dx) + abs(dy) > max_range:
                    continue
                nx, ny = x + dx, y + dy
                if self.is_passable(nx, ny):
                    result.append((nx, ny))
        return result

    def tiles_in_radius(self, x: int, y: int, radius: int) -> list[tuple[int, int]]:
        """All tiles (passable or not, but in-bounds) within Manhattan radius."""
        result: list[tuple[int, int]] = []
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if abs(dx) + abs(dy) > radius:
                    continue
                nx, ny = x + dx, y + dy
                if self.in_bounds(nx, ny):
                    result.append((nx, ny))
        return result

    def all_passable(self) -> Iterator[tuple[int, int]]:
        for (x, y), t in self._tiles.items():
            if t not in (TileType.WALL, TileType.FURNITURE):
                yield x, y

    def get_tile(self, x: int, y: int) -> TileType:
        return self._tiles.get((x, y), TileType.FLOOR)

    # -- Map display character ---------------------------------------------------

    def tile_char(self, x: int, y: int) -> str:
        """Return a single display character for the tile at (x, y)."""
        t = self.get_tile(x, y)
        if t == TileType.WALL:
            return "#"
        if t == TileType.FURNITURE:
            return "T"
        if t == TileType.DOOR:
            return "D"
        return "."

    # -- Factory methods for named maps ------------------------------------------

    @classmethod
    def create_arena(cls, width: int = 12, height: int = 10) -> BattleGrid:
        """Standard open arena — flat rectangle, no obstacles."""
        return cls(width=width, height=height)

    @classmethod
    def create_tavern(cls) -> BattleGrid:
        r"""8×8 tavern interior with walls, tables, and a bar counter.

        Layout::

              0 1 2 3 4 5 6 7
           0  # # # # # # # #
           1  # . . . . . . #
           2  # . T . . T . #
           3  # . . . . . . #
           4  # B B B . . . #
           5  # . . . . T . #
           6  # . . . . . . #
           7  # # # D D # # #

        Legend: # wall, T table, B bar counter, D door, . floor
        """
        grid = cls(width=8, height=8)

        # Perimeter walls
        for x in range(8):
            grid._tiles[(x, 0)] = TileType.WALL
            grid._tiles[(x, 7)] = TileType.WALL
        for y in range(8):
            grid._tiles[(0, y)] = TileType.WALL
            grid._tiles[(7, y)] = TileType.WALL

        # Doors in south wall (passable entry points)
        grid._tiles[(3, 7)] = TileType.DOOR
        grid._tiles[(4, 7)] = TileType.DOOR

        # Tables (impassable furniture)
        grid._tiles[(2, 2)] = TileType.FURNITURE
        grid._tiles[(5, 2)] = TileType.FURNITURE
        grid._tiles[(5, 5)] = TileType.FURNITURE

        # Bar counter (impassable furniture along west side)
        grid._tiles[(1, 4)] = TileType.FURNITURE
        grid._tiles[(2, 4)] = TileType.FURNITURE
        grid._tiles[(3, 4)] = TileType.FURNITURE

        return grid
