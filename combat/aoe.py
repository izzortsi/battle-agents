"""Area-of-effect pattern resolution for abilities.

Five patterns are supported:
  single — just the target tile
  line   — 5 tiles from caster toward target along the dominant axis
  cross  — + shape centred on target (5 tiles)
  radius — 3x3 centred on target (up to 9 tiles)
  cone   — fan shape, 3-wide at target distance

All functions return a list of (x, y) tuples filtered for passable tiles,
with the target tile always first (if passable).
"""

from __future__ import annotations

from world.battle_grid import BattleGrid


def get_affected_tiles(
    origin: tuple[int, int],
    target: tuple[int, int],
    pattern: str,
    grid: BattleGrid,
) -> list[tuple[int, int]]:
    """Return passable tiles affected by *pattern* from *origin* aimed at *target*."""
    pat = pattern.lower().strip()
    if pat == "single":
        return _single(target, grid)
    if pat == "line":
        return _line(origin, target, grid)
    if pat == "cross":
        return _cross(target, grid)
    if pat == "radius":
        return _radius(target, grid)
    if pat == "cone":
        return _cone(origin, target, grid)
    # Unknown pattern -> treat as single
    return _single(target, grid)


# ---------------------------------------------------------------------------
# Pattern implementations
# ---------------------------------------------------------------------------


def _single(target: tuple[int, int], grid: BattleGrid) -> list[tuple[int, int]]:
    """Just the target tile."""
    tx, ty = target
    if grid.is_passable(tx, ty):
        return [(tx, ty)]
    return []


def _line(
    origin: tuple[int, int],
    target: tuple[int, int],
    grid: BattleGrid,
) -> list[tuple[int, int]]:
    """5 tiles from caster toward target along the dominant axis."""
    ox, oy = origin
    tx, ty = target

    dx = tx - ox
    dy = ty - oy

    # Determine step direction along dominant axis
    if abs(dx) >= abs(dy):
        sx, sy = (1 if dx > 0 else -1), 0
    else:
        sx, sy = 0, (1 if dy > 0 else -1)

    tiles: list[tuple[int, int]] = []
    # Start one step from origin, lay 5 tiles
    for i in range(1, 6):
        nx, ny = ox + sx * i, oy + sy * i
        if grid.is_passable(nx, ny):
            tiles.append((nx, ny))

    # Ensure target tile is first if present
    return _target_first(tiles, target)


def _cross(target: tuple[int, int], grid: BattleGrid) -> list[tuple[int, int]]:
    """+ shape centred on target — centre + 4 cardinal neighbours (5 tiles)."""
    tx, ty = target
    offsets = [(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)]
    tiles = [
        (tx + dx, ty + dy) for dx, dy in offsets if grid.is_passable(tx + dx, ty + dy)
    ]
    return _target_first(tiles, target)


def _radius(target: tuple[int, int], grid: BattleGrid) -> list[tuple[int, int]]:
    """3x3 centred on target (up to 9 tiles)."""
    tx, ty = target
    tiles: list[tuple[int, int]] = []
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            nx, ny = tx + dx, ty + dy
            if grid.is_passable(nx, ny):
                tiles.append((nx, ny))
    return _target_first(tiles, target)


def _cone(
    origin: tuple[int, int],
    target: tuple[int, int],
    grid: BattleGrid,
) -> list[tuple[int, int]]:
    """Fan shape — 1 tile at origin+1, widening to 3 tiles at target distance.

    The cone extends along the dominant axis from origin toward target.
    At each step i from 1..dist, the spread is floor(i * 2 / dist) tiles
    to each side of the central line, up to 1 tile wide.
    """
    ox, oy = origin
    tx, ty = target

    dx = tx - ox
    dy = ty - oy
    dist = abs(dx) + abs(dy)
    if dist == 0:
        return _single(target, grid)

    # Determine primary and perpendicular step directions
    if abs(dx) >= abs(dy):
        sx, sy = (1 if dx > 0 else -1), 0
        px, py = 0, 1  # perpendicular
    else:
        sx, sy = 0, (1 if dy > 0 else -1)
        px, py = 1, 0  # perpendicular

    tiles: list[tuple[int, int]] = []
    for i in range(1, dist + 1):
        cx, cy = ox + sx * i, oy + sy * i
        # Spread widens linearly: 0 at start, 1 at end
        spread = max(0, (i * 2) // dist) if dist > 1 else 0
        spread = min(spread, 1)  # cap at 1 to keep it a 3-wide fan

        if grid.is_passable(cx, cy):
            tiles.append((cx, cy))

        for s in range(1, spread + 1):
            left = (cx + px * s, cy + py * s)
            right = (cx - px * s, cy - py * s)
            if grid.is_passable(*left):
                tiles.append(left)
            if grid.is_passable(*right):
                tiles.append(right)

    return _target_first(tiles, target)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _target_first(
    tiles: list[tuple[int, int]],
    target: tuple[int, int],
) -> list[tuple[int, int]]:
    """Reorder so *target* is first, if present."""
    if target in tiles:
        tiles.remove(target)
        tiles.insert(0, target)
    return tiles
