#!/bin/bash
# Convert app.svg → app.png (512×512) for Electron icon.
# Tries rsvg-convert, then magick, then inkscape.

set -euo pipefail
cd "$(dirname "$0")"

SRC="app.svg"
OUT="app.png"
SIZE=512

if [ ! -f "$SRC" ]; then
  echo "Error: $SRC not found in $(pwd)" >&2
  exit 1
fi

if command -v rsvg-convert &>/dev/null; then
  rsvg-convert -w "$SIZE" -h "$SIZE" "$SRC" > "$OUT"
elif command -v magick &>/dev/null; then
  magick "$SRC" -resize "${SIZE}x${SIZE}" "$OUT"
elif command -v inkscape &>/dev/null; then
  inkscape "$SRC" -w "$SIZE" -h "$SIZE" -o "$OUT"
else
  echo "Error: no SVG converter found. Install librsvg, imagemagick, or inkscape." >&2
  exit 1
fi

echo "Created $OUT ($(stat -c%s "$OUT") bytes)"
