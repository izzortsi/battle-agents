/**
 * constants.js — Color maps, status visuals, SVG symbol definitions.
 */

const CELL_SIZE = 52;
const SPRITE_W = 36;
const SPRITE_H = 42;

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
