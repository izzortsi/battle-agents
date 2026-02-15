/**
 * constants.js — Color maps, status visuals, SVG symbol definitions.
 */

const CELL_SIZE = 52;
const SPRITE_W = 36;
const SPRITE_H = 42;

// Spritesheet constants (RPG Maker style: 3 cols × 4 rows, each frame 32×32)
const SS_FRAME_W = 32;
const SS_FRAME_H = 32;
const SS_COLS = 3;
const SS_SHEET_W = SS_FRAME_W * SS_COLS; // 96
const SS_SHEET_H = SS_FRAME_H * 4;       // 128

// Row indices for facing direction
const SS_DIR = { down: 0, left: 1, right: 2, up: 3 };

// Idle frame column
const SS_IDLE_COL = 1;

const CLASS_PALETTES = {
  warrior: { primary: '#708090', secondary: '#8B0000', accent: '#cd5c5c' },
  mage:    { primary: '#4B0082', secondary: '#4169E1', accent: '#9370db' },
  rogue:   { primary: '#013220', secondary: '#2f4f4f', accent: '#556b2f' },
  healer:  { primary: '#DAA520', secondary: '#FFF8DC', accent: '#f0e68c' },
};

const STATUS_VISUALS = {
  poison:  { icon: '\u2620', color: '#44bb44', animation: 'status-poison' },
  burn:    { icon: '\uD83D\uDD25', color: '#ff6633', animation: 'status-burn' },
  freeze:  { icon: '\u2744', color: '#88ddff', animation: 'status-freeze' },
  stun:    { icon: '\u2B50', color: '#ffdd44', animation: 'status-stun' },
  blind:   { icon: '\uD83D\uDC41', color: '#666',    animation: 'status-blind' },
  defend:  { icon: '\uD83D\uDEE1', color: '#4488ff', animation: 'status-defend' },
  enrage:  { icon: '\uD83D\uDCA2', color: '#ff2222', animation: 'status-enrage' },
  haste:   { icon: '\u26A1', color: '#44ddff', animation: 'status-haste' },
  root:    { icon: '\uD83C\uDF3F', color: '#228B22', animation: 'status-poison' },
  entangle:{ icon: '\uD83C\uDF3F', color: '#228B22', animation: 'status-poison' },
};

const STATUS_DEFAULT = { icon: '\u2B24', color: '#888', animation: '' };

/**
 * Tile type visual styles.
 * Each tile type has two fill colors (even/odd checkerboard), a stroke, and
 * optional stroke-width override.  Furniture tiles also get an inner detail
 * rect rendered on top.
 */
const TILE_COLORS = {
  floor:     { even: '#1e1e3a', odd: '#222244', stroke: '#2a2a4a', strokeWidth: 0.5 },
  wall:      { even: '#3a2a1a', odd: '#44321e', stroke: '#5a4530', strokeWidth: 1.0 },
  furniture: { even: '#3a2818', odd: '#44301c', stroke: '#5a4020', strokeWidth: 0.5,
               detail: '#6b5030' },
  door:      { even: '#2a2a3a', odd: '#303044', stroke: '#4a4a6a', strokeWidth: 0.5,
               dashArray: '3 2' },
  stone:     { even: '#282848', odd: '#2e2e52', stroke: '#40406a', strokeWidth: 0.5 },
  pillar:    { even: '#352844', odd: '#3e2e50', stroke: '#52406a', strokeWidth: 1.0,
               detail: '#6a5a88', detailShape: 'circle' },
  gravel:    { even: '#302828', odd: '#382e2e', stroke: '#4a3a38', strokeWidth: 0.5,
               detail: '#5a4a44', detailShape: 'speckle' },
  cracked:   { even: '#22202e', odd: '#282636', stroke: '#38344a', strokeWidth: 0.5,
               detail: '#5a506a', detailShape: 'cracks' },
  rune:      { even: '#1c1c38', odd: '#201e40', stroke: '#2a2a4a', strokeWidth: 0.5,
               detail: '#9b8aff', detailShape: 'rune' },
};

/**
 * Rune glyph SVG paths — 4 distinct designs drawn within a 0-1 normalised
 * coordinate space (scaled at render time to fit the cell).
 * Each glyph is an array of SVG path-data strings.
 */
const RUNE_GLYPHS = [
  // Glyph 0 — Arcane circle: concentric rings + cross
  {
    paths: [],
    circles: [
      { cx: 0.5, cy: 0.5, r: 0.40 },
      { cx: 0.5, cy: 0.5, r: 0.25 },
    ],
    lines: [
      { x1: 0.5, y1: 0.08, x2: 0.5, y2: 0.92 },
      { x1: 0.08, y1: 0.5, x2: 0.92, y2: 0.5 },
    ],
  },
  // Glyph 1 — Diamond ward: rotated square + inner dot
  {
    paths: ['M 0.5 0.1 L 0.9 0.5 L 0.5 0.9 L 0.1 0.5 Z'],
    circles: [
      { cx: 0.5, cy: 0.5, r: 0.10 },
    ],
    lines: [
      { x1: 0.5, y1: 0.1, x2: 0.5, y2: 0.9 },
      { x1: 0.1, y1: 0.5, x2: 0.9, y2: 0.5 },
    ],
  },
  // Glyph 2 — Star hex: 6-pointed star
  {
    paths: [
      'M 0.5 0.1 L 0.72 0.37 L 0.95 0.37 L 0.78 0.57 L 0.85 0.82 L 0.5 0.68 L 0.15 0.82 L 0.22 0.57 L 0.05 0.37 L 0.28 0.37 Z',
    ],
    circles: [
      { cx: 0.5, cy: 0.47, r: 0.12 },
    ],
    lines: [],
  },
  // Glyph 3 — Triangle ward: nested triangles
  {
    paths: [
      'M 0.5 0.1 L 0.9 0.85 L 0.1 0.85 Z',
      'M 0.5 0.35 L 0.72 0.75 L 0.28 0.75 Z',
    ],
    circles: [
      { cx: 0.5, cy: 0.6, r: 0.06 },
    ],
    lines: [],
  },
];

/**
 * SVG symbol definitions — class silhouettes.
 * Each symbol is a 36x42 viewBox.
 */
const SVG_DEFS = `
<!-- Warrior: broad body + shield + sword -->
<symbol id="silhouette-warrior" viewBox="0 0 36 42">
  <!-- Body -->
  <rect class="silhouette-body" x="8" y="12" width="20" height="22" rx="3"/>
  <!-- Head -->
  <circle class="silhouette-body" cx="18" cy="8" r="6"/>
  <!-- Helmet crest -->
  <rect class="silhouette-detail" x="15" y="2" width="6" height="4" rx="1"/>
  <!-- Shield (left) -->
  <rect class="silhouette-detail" x="2" y="16" width="8" height="12" rx="2"/>
  <!-- Sword (right) -->
  <rect class="silhouette-accent" x="28" y="10" width="3" height="20" rx="1"/>
  <rect class="silhouette-accent" x="26" y="10" width="7" height="3" rx="1"/>
  <!-- Legs -->
  <rect class="silhouette-body" x="10" y="34" width="6" height="8" rx="2"/>
  <rect class="silhouette-body" x="20" y="34" width="6" height="8" rx="2"/>
</symbol>

<!-- Mage: robed body + pointed hat + staff + orb -->
<symbol id="silhouette-mage" viewBox="0 0 36 42">
  <!-- Robe body (triangle) -->
  <polygon class="silhouette-body" points="18,14 4,40 32,40"/>
  <!-- Head -->
  <circle class="silhouette-body" cx="18" cy="10" r="5"/>
  <!-- Pointed hat -->
  <polygon class="silhouette-detail" points="18,0 12,10 24,10"/>
  <!-- Staff (right) -->
  <rect class="silhouette-accent" x="30" y="6" width="2" height="34" rx="1"/>
  <!-- Orb on staff -->
  <circle class="silhouette-accent" cx="31" cy="6" r="3"/>
</symbol>

<!-- Rogue: slim body + hood + dagger -->
<symbol id="silhouette-rogue" viewBox="0 0 36 42">
  <!-- Slim body -->
  <rect class="silhouette-body" x="11" y="14" width="14" height="18" rx="3"/>
  <!-- Head -->
  <circle class="silhouette-body" cx="18" cy="9" r="5"/>
  <!-- Hood -->
  <path class="silhouette-detail" d="M12,10 Q18,2 24,10 Q22,6 18,5 Q14,6 12,10Z"/>
  <!-- Dagger (right) -->
  <polygon class="silhouette-accent" points="30,18 32,16 34,24 32,24"/>
  <!-- Dagger (left) -->
  <polygon class="silhouette-accent" points="6,18 4,16 2,24 4,24"/>
  <!-- Legs (slim) -->
  <rect class="silhouette-body" x="12" y="32" width="5" height="10" rx="2"/>
  <rect class="silhouette-body" x="19" y="32" width="5" height="10" rx="2"/>
</symbol>

<!-- Healer: body + halo + cross-staff -->
<symbol id="silhouette-healer" viewBox="0 0 36 42">
  <!-- Body -->
  <polygon class="silhouette-body" points="18,14 6,38 30,38"/>
  <!-- Head -->
  <circle class="silhouette-body" cx="18" cy="9" r="5"/>
  <!-- Halo -->
  <ellipse class="silhouette-accent" cx="18" cy="4" rx="7" ry="2" fill="none" stroke-width="1.5"/>
  <!-- Cross-staff -->
  <rect class="silhouette-detail" x="31" y="8" width="2" height="30" rx="1"/>
  <rect class="silhouette-detail" x="28" y="12" width="8" height="2" rx="1"/>
</symbol>
`;

function getStatusVisual(statusType) {
  return STATUS_VISUALS[statusType] || STATUS_DEFAULT;
}
