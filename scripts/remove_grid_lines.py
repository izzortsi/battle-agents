#!/usr/bin/env python3
"""Remove grid lines from sprite sheet images.

Handles two kinds of grid lines:

1. **Extra rows/columns** – thin solid-colour lines inserted between sprite
   cells that make the image larger than expected.  These are detected and
   stripped out.

2. **Semi-transparent overlays** – coloured lines composited *on top* of
   the sprite data (the image stays the same size but certain rows/columns
   have an overlay blended in).  These are detected by compositing the image
   on a white background and searching for rows/columns with a distinctive
   uniform colour tint, then the overlay is mathematically subtracted to
   recover the original pixels.

Usage:
    python scripts/remove_grid_lines.py INPUT [-o OUTPUT] [options]

Examples:
    # Auto-detect and remove grid lines, overwrite in place
    python scripts/remove_grid_lines.py spritesheet.png

    # Write to a separate output file
    python scripts/remove_grid_lines.py spritesheet.png -o clean.png

    # Process all PNGs in a directory (overwrites in place)
    python scripts/remove_grid_lines.py sprites/*.png

    # Validate output matches expected sprite sheet size
    python scripts/remove_grid_lines.py spritesheet.png --expected-size 96x128
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image


# ---------------------------------------------------------------------------
# Strategy 1 – detect & strip extra rows/columns (solid opaque grid lines)
# ---------------------------------------------------------------------------


def detect_solid_grid_lines(
    arr: np.ndarray,
    grid_color: tuple[int, int, int] = (0, 0, 0),
    tolerance: int = 30,
) -> tuple[list[int], list[int]]:
    """Return row/column indices that are solid-colour grid lines."""
    h, w = arr.shape[:2]
    has_alpha = arr.shape[2] == 4
    gc = np.array(grid_color, dtype=np.float64)
    min_coverage = 0.80

    grid_rows: list[int] = []
    grid_cols: list[int] = []

    for y in range(h):
        row = arr[y]
        if has_alpha:
            opaque_mask = row[:, 3] > 0
            n_opaque = int(np.sum(opaque_mask))
            if n_opaque < w * min_coverage:
                continue
            rgb = row[opaque_mask, :3].astype(np.float64)
        else:
            rgb = row[:, :3].astype(np.float64)
        dists = np.sqrt(np.sum((rgb - gc) ** 2, axis=1))
        if np.all(dists <= tolerance):
            grid_rows.append(y)

    for x in range(w):
        col = arr[:, x]
        if has_alpha:
            opaque_mask = col[:, 3] > 0
            n_opaque = int(np.sum(opaque_mask))
            if n_opaque < h * min_coverage:
                continue
            rgb = col[opaque_mask, :3].astype(np.float64)
        else:
            rgb = col[:, :3].astype(np.float64)
        dists = np.sqrt(np.sum((rgb - gc) ** 2, axis=1))
        if np.all(dists <= tolerance):
            grid_cols.append(x)

    grid_rows = _filter_grid_indices(grid_rows, h)
    grid_cols = _filter_grid_indices(grid_cols, w)
    return grid_rows, grid_cols


# ---------------------------------------------------------------------------
# Strategy 2 – detect & remove semi-transparent overlay grid lines
# ---------------------------------------------------------------------------


def _composite_on_white(arr: np.ndarray) -> np.ndarray:
    """Composite RGBA image array onto a white background, returning RGB uint8."""
    h, w = arr.shape[:2]
    white = np.ones((h, w, 3), dtype=np.float64) * 255
    alpha = arr[:, :, 3:4].astype(np.float64) / 255.0
    rgb = arr[:, :, :3].astype(np.float64)
    return (rgb * alpha + white * (1.0 - alpha)).astype(np.uint8)


def detect_overlay_grid_lines(
    arr: np.ndarray,
) -> tuple[list[int], list[int]]:
    """Detect semi-transparent overlay grid lines by uniformity analysis.

    Composites the image on white and finds rows/columns that are
    *unusually uniform* compared to the image median (low per-pixel
    variance).  Grid lines -- regardless of colour -- produce a flat band
    of similar colour, while sprite rows have high variance.

    Detected lines are then expanded to adjacent uniform neighbours
    (to catch 2-4 px wide grids) and filtered to keep only evenly-spaced
    interior groups.

    Returns (row_indices, col_indices).
    """
    comp = _composite_on_white(arr)
    h, w = arr.shape[:2]

    # --- Per-row / per-column statistics ------------------------------------
    row_stds = np.array([comp[y].astype(float).std(axis=0).mean() for y in range(h)])
    col_stds = np.array([comp[:, x].astype(float).std(axis=0).mean() for x in range(w)])
    median_row_std = float(np.median(row_stds))
    median_col_std = float(np.median(col_stds))

    # Alpha coverage: fraction of non-transparent pixels per row/col.
    row_alpha_frac = np.array([np.sum(arr[y, :, 3] > 0) / w for y in range(h)])
    col_alpha_frac = np.array([np.sum(arr[:, x, 3] > 0) / h for x in range(w)])

    # --- Shared helper: alpha-jump check ------------------------------------
    alpha_jump = 0.25

    def _alpha_jump_ok(frac_arr: np.ndarray, idx: int, total: int) -> bool:
        window = 3
        neighbours = []
        for d in range(-window, window + 1):
            n = idx + d
            if n != idx and 0 <= n < total:
                neighbours.append(frac_arr[n])
        if not neighbours:
            return False
        avg_neighbour = float(np.mean(neighbours))
        return frac_arr[idx] - avg_neighbour > alpha_jump

    # --- Method A: colour-tint detection (catches teal / coloured overlays) --
    g_offset = 5
    b_offset = 10
    tint_frac = 0.50
    tint_uniformity = 0.78
    tint_strict = 0.55  # below this: definitely grid; between strict and uniformity: needs alpha jump

    tint_rows: list[int] = []
    for y in range(h):
        row = comp[y].astype(np.float64)
        teal = (row[:, 1] > row[:, 0] + g_offset) & (row[:, 2] > row[:, 0] + b_offset)
        if np.sum(teal) <= w * tint_frac:
            continue
        ratio = row_stds[y] / median_row_std
        if ratio < tint_strict:
            tint_rows.append(y)
        elif ratio < tint_uniformity and _alpha_jump_ok(row_alpha_frac, y, h):
            tint_rows.append(y)

    tint_cols: list[int] = []
    for x in range(w):
        col = comp[:, x].astype(np.float64)
        teal = (col[:, 1] > col[:, 0] + g_offset) & (col[:, 2] > col[:, 0] + b_offset)
        if np.sum(teal) <= h * tint_frac:
            continue
        ratio = col_stds[x] / median_col_std
        if ratio < tint_strict:
            tint_cols.append(x)
        elif ratio < tint_uniformity and _alpha_jump_ok(col_alpha_frac, x, w):
            tint_cols.append(x)

    # --- Method B: alpha-jump detection (catches white / neutral overlays) ---
    strict_uniformity = 0.35

    alpha_rows = [
        y
        for y in range(h)
        if (
            row_stds[y] < median_row_std * strict_uniformity
            and _alpha_jump_ok(row_alpha_frac, y, h)
        )
    ]
    alpha_cols = [
        x
        for x in range(w)
        if (
            col_stds[x] < median_col_std * strict_uniformity
            and _alpha_jump_ok(col_alpha_frac, x, w)
        )
    ]

    # --- Method C: full-coverage detection (catches dense overlay grids) -----
    # Rows/cols where EVERY pixel has alpha > 0 (100% coverage) AND the
    # composited row/col is very uniform.  This catches overlay grid lines
    # even when sprites are dense, because sprite rows/cols rarely have
    # 100% alpha coverage across the full image extent.
    full_uniformity = 0.20  # very strict: must be extremely uniform

    full_rows = [
        y
        for y in range(h)
        if (
            row_alpha_frac[y] >= 0.99 and row_stds[y] < median_row_std * full_uniformity
        )
    ]
    full_cols = [
        x
        for x in range(w)
        if (
            col_alpha_frac[x] >= 0.99 and col_stds[x] < median_col_std * full_uniformity
        )
    ]

    # --- Filter each method separately, then merge ---------------------------
    # Filtering each method individually avoids noise from one method
    # breaking the even-spacing check of another method's clean detections.
    filtered_tint_rows = _filter_grid_indices(tint_rows, h)
    filtered_tint_cols = _filter_grid_indices(tint_cols, w)
    filtered_alpha_rows = _filter_grid_indices(alpha_rows, h)
    filtered_alpha_cols = _filter_grid_indices(alpha_cols, w)
    filtered_full_rows = _filter_grid_indices(full_rows, h)
    filtered_full_cols = _filter_grid_indices(full_cols, w)

    candidate_rows = sorted(
        set(filtered_tint_rows) | set(filtered_alpha_rows) | set(filtered_full_rows)
    )
    candidate_cols = sorted(
        set(filtered_tint_cols) | set(filtered_alpha_cols) | set(filtered_full_cols)
    )

    if not candidate_rows and not candidate_cols:
        return [], []

    # --- Targeted expansion: add +/-1 neighbours from any method's raw set --
    all_method_rows = sorted(set(tint_rows) | set(alpha_rows) | set(full_rows))
    all_method_cols = sorted(set(tint_cols) | set(alpha_cols) | set(full_cols))

    def _expand_from_methods(
        indices: list[int],
        method_indices: list[int],
        total: int,
    ) -> list[int]:
        method_set = set(method_indices)
        expanded = set(indices)
        for idx in indices:
            for n in (idx - 1, idx + 1):
                if 0 <= n < total and n in method_set:
                    expanded.add(n)
        return sorted(expanded)

    expanded_rows = _expand_from_methods(candidate_rows, all_method_rows, h)
    expanded_cols = _expand_from_methods(candidate_cols, all_method_cols, w)

    # Final re-filter.
    expanded_rows = _filter_grid_indices(expanded_rows, h)
    expanded_cols = _filter_grid_indices(expanded_cols, w)

    return expanded_rows, expanded_cols


def replace_with_neighbours(
    arr: np.ndarray,
    row_indices: list[int],
    col_indices: list[int],
) -> np.ndarray:
    """Replace grid-line rows/columns with the average of their neighbours.

    For each affected row, every pixel is replaced by the average of the
    pixel above and below it.  For columns, the average of left and right.
    At intersections (row AND column), average all four diagonal neighbours.

    This is more robust than trying to mathematically reverse an alpha
    blend, which is numerically unstable.
    """
    out = arr.copy().astype(np.float64)
    h, w = arr.shape[:2]

    row_set = set(row_indices)
    col_set = set(col_indices)

    # Replace grid-line rows (skip intersections for now)
    for y in row_indices:
        y_above = y - 1
        y_below = y + 1
        # Walk outward if the neighbour is also a grid line
        while y_above >= 0 and y_above in row_set:
            y_above -= 1
        while y_below < h and y_below in row_set:
            y_below += 1

        for x in range(w):
            if x in col_set:
                continue  # handle intersections separately
            above = out[y_above, x] if y_above >= 0 else np.zeros(4)
            below = out[y_below, x] if y_below < h else np.zeros(4)
            # If one neighbour is transparent and the other isn't, use the opaque one
            if above[3] < 1 and below[3] < 1:
                out[y, x] = [0, 0, 0, 0]
            elif above[3] < 1:
                out[y, x] = below
            elif below[3] < 1:
                out[y, x] = above
            else:
                out[y, x] = (above + below) / 2.0

    # Replace grid-line columns (skip intersections for now)
    for x in col_indices:
        x_left = x - 1
        x_right = x + 1
        while x_left >= 0 and x_left in col_set:
            x_left -= 1
        while x_right < w and x_right in col_set:
            x_right += 1

        for y in range(h):
            if y in row_set:
                continue  # handle intersections separately
            left = out[y, x_left] if x_left >= 0 else np.zeros(4)
            right = out[y, x_right] if x_right < w else np.zeros(4)
            if left[3] < 1 and right[3] < 1:
                out[y, x] = [0, 0, 0, 0]
            elif left[3] < 1:
                out[y, x] = right
            elif right[3] < 1:
                out[y, x] = left
            else:
                out[y, x] = (left + right) / 2.0

    # Handle intersections: average from 4 diagonal neighbours
    for y in row_indices:
        y_above = y - 1
        y_below = y + 1
        while y_above >= 0 and y_above in row_set:
            y_above -= 1
        while y_below < h and y_below in row_set:
            y_below += 1

        for x in col_indices:
            x_left = x - 1
            x_right = x + 1
            while x_left >= 0 and x_left in col_set:
                x_left -= 1
            while x_right < w and x_right in col_set:
                x_right += 1

            neighbours = []
            if y_above >= 0 and x_left >= 0:
                neighbours.append(out[y_above, x_left])
            if y_above >= 0 and x_right < w:
                neighbours.append(out[y_above, x_right])
            if y_below < h and x_left >= 0:
                neighbours.append(out[y_below, x_left])
            if y_below < h and x_right < w:
                neighbours.append(out[y_below, x_right])

            opaque = [n for n in neighbours if n[3] > 0]
            if opaque:
                out[y, x] = np.mean(opaque, axis=0)
            else:
                out[y, x] = [0, 0, 0, 0]

    return np.clip(out, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _filter_grid_indices(indices: list[int], total: int) -> list[int]:
    """Keep only indices that form evenly-spaced interior grid lines."""
    if not indices:
        return []

    groups: list[list[int]] = []
    current_group: list[int] = [indices[0]]
    for i in range(1, len(indices)):
        if indices[i] == indices[i - 1] + 1:
            current_group.append(indices[i])
        else:
            groups.append(current_group)
            current_group = [indices[i]]
    groups.append(current_group)

    # Remove edge groups
    interior_groups = [g for g in groups if g[0] > 0 and g[-1] < total - 1]
    if not interior_groups:
        return []

    # Check for roughly even spacing
    if len(interior_groups) >= 2:
        centres = [(g[0] + g[-1]) / 2.0 for g in interior_groups]
        spacings = [centres[i + 1] - centres[i] for i in range(len(centres) - 1)]
        avg_spacing = float(np.mean(spacings))
        if not all(abs(s - avg_spacing) / max(avg_spacing, 1) < 0.30 for s in spacings):
            return []

    return [idx for g in interior_groups for idx in g]


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def remove_grid_lines(
    img: Image.Image,
    grid_color: tuple[int, int, int] = (0, 0, 0),
    tolerance: int = 30,
    expected_size: tuple[int, int] | None = None,
) -> Image.Image:
    """Return a new image with grid lines removed.

    Tries two strategies in order:
    1. Detect solid-colour extra rows/columns and strip them.
    2. Detect semi-transparent overlay lines and subtract them.
    """
    arr = np.array(img.convert("RGBA"))

    # --- Strategy 1: strip extra solid-colour rows/columns -------------------
    solid_rows, solid_cols = detect_solid_grid_lines(arr, grid_color, tolerance)
    if solid_rows or solid_cols:
        print(
            f"  [solid] Detected {len(solid_rows)} row(s) and {len(solid_cols)} col(s)."
        )
        keep_rows = sorted(set(range(arr.shape[0])) - set(solid_rows))
        keep_cols = sorted(set(range(arr.shape[1])) - set(solid_cols))
        cleaned = arr[np.ix_(keep_rows, keep_cols)]
        result = Image.fromarray(cleaned, "RGBA")
        _report_size(result, expected_size)
        return result

    # --- Strategy 2: detect overlay lines via colour analysis ----------------
    ov_rows, ov_cols = detect_overlay_grid_lines(arr)
    if ov_rows or ov_cols:
        print(
            f"  [overlay] Detected {len(ov_rows)} row(s) and {len(ov_cols)} col(s). "
            f"Replacing with neighbour interpolation."
        )
        cleaned = replace_with_neighbours(arr, ov_rows, ov_cols)
        result = Image.fromarray(cleaned, "RGBA")
        _report_size(result, expected_size)
        return result

    print("  No grid lines detected – image returned unchanged.")
    return img


def _report_size(
    result: Image.Image,
    expected_size: tuple[int, int] | None,
) -> None:
    if expected_size and result.size != expected_size:
        print(
            f"  WARNING: Result size {result.size} doesn't match expected "
            f"{expected_size}."
        )
    else:
        print(f"  Output size: {result.size}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove grid lines from sprite sheet images.",
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Input PNG file(s). Shell globs are supported.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output file (only valid with a single input). "
        "If omitted, the input file is overwritten.",
    )
    parser.add_argument(
        "--grid-color",
        nargs=3,
        type=int,
        default=[0, 0, 0],
        metavar=("R", "G", "B"),
        help="RGB colour of solid grid lines (default: 0 0 0 = black). "
        "Only used for Strategy 1 (solid lines).",
    )
    parser.add_argument(
        "--tolerance",
        type=int,
        default=30,
        help="Max Euclidean distance from grid colour (default: 30).",
    )
    parser.add_argument(
        "--expected-size",
        type=str,
        default=None,
        help="Expected output size as WxH, e.g. 96x128. Warns on mismatch.",
    )

    args = parser.parse_args()

    if args.output and len(args.inputs) > 1:
        print(
            "ERROR: --output can only be used with a single input file.",
            file=sys.stderr,
        )
        sys.exit(1)

    grid_color = tuple(args.grid_color)
    expected_size = None
    if args.expected_size:
        w, h = args.expected_size.split("x")
        expected_size = (int(w), int(h))

    for input_path in args.inputs:
        p = Path(input_path)
        if not p.exists():
            print(f"Skipping {p} – file not found.", file=sys.stderr)
            continue

        print(f"Processing: {p}")
        img = Image.open(p)
        cleaned = remove_grid_lines(
            img,
            grid_color=grid_color,
            tolerance=args.tolerance,
            expected_size=expected_size,
        )

        out_path = Path(args.output) if args.output else p
        cleaned.save(out_path)
        print(f"  Saved: {out_path}")


if __name__ == "__main__":
    main()
