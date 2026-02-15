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
    STONE = "stone"  # cosmetic floor variant — cool grey (passable)
    PILLAR = "pillar"  # impassable stone column
    GRAVEL = "gravel"  # cosmetic floor variant — warm sandy (passable)
    CRACKED = "cracked"  # cosmetic damaged stone (passable)
    RUNE = "rune"  # magical glyph on floor (passable, cosmetic)


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

    _IMPASSABLE = frozenset({TileType.WALL, TileType.FURNITURE, TileType.PILLAR})

    def is_passable(self, x: int, y: int) -> bool:
        t = self._tiles.get((x, y))
        return self.in_bounds(x, y) and t not in self._IMPASSABLE

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
            if t not in self._IMPASSABLE:
                yield x, y

    def get_tile(self, x: int, y: int) -> TileType:
        return self._tiles.get((x, y), TileType.FLOOR)

    # -- Serialisation ----------------------------------------------------------

    def serialize_tiles(self) -> list[list[str]]:
        """Return a row-major 2D array of tile type strings for the frontend.

        Result is ``tiles[y][x]`` where each value is a :class:`TileType`
        string (``"floor"``, ``"wall"``, ``"stone"``, ``"pillar"``,
        ``"gravel"``, ``"cracked"``, ``"rune"``, etc.).
        """
        return [
            [self._tiles.get((x, y), TileType.FLOOR).value for x in range(self.width)]
            for y in range(self.height)
        ]

    # -- Map display character ---------------------------------------------------

    def tile_char(self, x: int, y: int) -> str:
        """Return a single display character for the tile at (x, y)."""
        t = self.get_tile(x, y)
        _CHARS = {
            TileType.WALL: "#",
            TileType.FURNITURE: "T",
            TileType.DOOR: "D",
            TileType.STONE: "s",
            TileType.PILLAR: "O",
            TileType.GRAVEL: ",",
            TileType.CRACKED: "x",
            TileType.RUNE: "*",
        }
        return _CHARS.get(t, ".")

    # -- Factory methods for named maps ------------------------------------------

    @classmethod
    def create_arena(cls, width: int = 12, height: int = 10) -> BattleGrid:
        r"""Combat arena with varied terrain, pillars, and rune glyphs.

        Default 12×10 layout::

              0 1 2 3 4 5 6 7 8 9 A B
           0  , s s s s s s s s s s ,
           1  s , . . . * . . . . , s
           2  s . x s . . . . s x . s
           3  s . s O . . . . O s . s
           4  s * . . . , , . . . * s
           5  s * . . . , , . . . * s
           6  s . s O . . . . O s . s
           7  s . x s . . . . s x . s
           8  s , . . . * . . . . , s
           9  , s s s s s s s s s s ,

        Legend: . floor  s stone  O pillar  , gravel
                x cracked  * rune
        ~116 passable / 120 total (97% open).
        """
        grid = cls(width=width, height=height)

        # --- Stone border ring (edges, cosmetic) ---
        for x in range(width):
            for y in range(height):
                on_edge_x = x == 0 or x == width - 1
                on_edge_y = y == 0 or y == height - 1

                # Corners get gravel (weathered look)
                if on_edge_x and on_edge_y:
                    grid._tiles[(x, y)] = TileType.GRAVEL
                    continue

                # Top/bottom edge
                if on_edge_y and not on_edge_x:
                    grid._tiles[(x, y)] = TileType.STONE
                # Left/right edge
                elif on_edge_x and not on_edge_y:
                    grid._tiles[(x, y)] = TileType.STONE

        # --- Gravel patches just inside the corners (weathered edges) ---
        for dx, dy in [(1, 1), (1, -2), (-2, 1), (-2, -2)]:
            gx = dx if dx >= 0 else width + dx
            gy = dy if dy >= 0 else height + dy
            if grid.in_bounds(gx, gy):
                grid._tiles[(gx, gy)] = TileType.GRAVEL

        # --- 4 symmetric pillars for tactical cover ---
        px1 = max(3, width // 4)
        px2 = min(width - 4, width - 1 - width // 4)
        py1 = max(3, height // 3)
        py2 = min(height - 4, height - 1 - height // 3)

        for px, py in [(px1, py1), (px2, py1), (px1, py2), (px2, py2)]:
            grid._tiles[(px, py)] = TileType.PILLAR

        # --- Stone accents adjacent to pillars ---
        for px, py in [(px1, py1), (px2, py1), (px1, py2), (px2, py2)]:
            accents = [(px - 1, py), (px, py - 1), (px, py + 1), (px + 1, py)]
            for ax, ay in accents:
                if (
                    grid.in_bounds(ax, ay)
                    and grid._tiles.get((ax, ay)) == TileType.FLOOR
                ):
                    if (ax + ay) % 2 == (px + py) % 2:
                        grid._tiles[(ax, ay)] = TileType.STONE

        # --- Cracked tiles near pillars and scattered across arena ---
        # Diagonal to each pillar (battle damage from impacts)
        for px, py in [(px1, py1), (px2, py1), (px1, py2), (px2, py2)]:
            for dx, dy in [(-1, -1), (1, 1), (1, -1), (-1, 1)]:
                cx, cy = px + dx, py + dy
                if (
                    grid.in_bounds(cx, cy)
                    and grid._tiles.get((cx, cy)) == TileType.FLOOR
                ):
                    grid._tiles[(cx, cy)] = TileType.CRACKED

        # Scattered cracks along the midlines (old battle scars)
        mid_x = width // 2
        mid_y = height // 2
        for offset in [-2, 2]:
            for cx, cy in [
                (mid_x + offset, mid_y),
                (mid_x, mid_y + offset),
            ]:
                if (
                    grid.in_bounds(cx, cy)
                    and grid._tiles.get((cx, cy)) == TileType.FLOOR
                ):
                    grid._tiles[(cx, cy)] = TileType.CRACKED

        # --- Gravel patches (worn-down areas) ---
        # Central cluster
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                gx, gy = mid_x + dx, mid_y + dy
                if (
                    grid.in_bounds(gx, gy)
                    and grid._tiles.get((gx, gy)) == TileType.FLOOR
                ):
                    grid._tiles[(gx, gy)] = TileType.GRAVEL

        # Gravel trail connecting pillars along the inner ring
        for px, py in [(px1, py1), (px2, py1), (px1, py2), (px2, py2)]:
            # Scatter gravel 2 tiles out from each pillar toward center
            toward_cx = 1 if px < mid_x else -1
            toward_cy = 1 if py < mid_y else -1
            for step in range(1, 3):
                gx, gy = px + toward_cx * step, py + toward_cy * step
                if (
                    grid.in_bounds(gx, gy)
                    and grid._tiles.get((gx, gy)) == TileType.FLOOR
                ):
                    grid._tiles[(gx, gy)] = TileType.GRAVEL

        # --- Rune glyphs in a symmetric pattern ---
        # Cardinal runes: midpoints of each edge (1 tile in)
        rune_positions = [
            (mid_x, 1),  # north
            (mid_x, height - 2),  # south
            (1, mid_y),  # west
            (width - 2, mid_y),  # east
        ]
        # Diagonal runes: between pillars and corners
        rune_positions += [
            (1, mid_y - 1),  # west upper
            (1, mid_y),  # west (already above, deduped by set)
            (width - 2, mid_y - 1),  # east upper
            (width - 2, mid_y),  # east (already above)
        ]
        seen: set[tuple[int, int]] = set()
        for rx, ry in rune_positions:
            if (rx, ry) in seen:
                continue
            seen.add((rx, ry))
            if grid.in_bounds(rx, ry) and grid._tiles.get((rx, ry)) in (
                TileType.FLOOR,
                TileType.STONE,
            ):
                grid._tiles[(rx, ry)] = TileType.RUNE

        return grid

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
