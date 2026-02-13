/**
 * sprites.js — SVG sprite factory. Creates and updates agent sprites from data.
 *
 * Supports two rendering modes:
 *   1. Spritesheet (agentData.sprite is set) — uses an <image> clipped to show
 *      one frame from a 3-col x 4-row RPG Maker–style spritesheet.
 *   2. SVG silhouette (no sprite) — uses <use> referencing class-based symbols.
 */

const SVG_NS = 'http://www.w3.org/2000/svg';

function svgEl(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    el.setAttribute(k, v);
  }
  return el;
}

/**
 * Inject <defs> symbols into the SVG.
 */
function injectDefs(svgRoot) {
  const defs = svgRoot.querySelector('#svg-defs');
  if (defs) defs.innerHTML = SVG_DEFS;
}

/**
 * Create tile grid rects.
 */
function createGridTiles(layerTiles, gridW, gridH) {
  layerTiles.innerHTML = '';
  for (let y = 0; y < gridH; y++) {
    for (let x = 0; x < gridW; x++) {
      const rect = svgEl('rect', {
        x: x * CELL_SIZE + 1,
        y: y * CELL_SIZE + 1,
        width: CELL_SIZE - 2,
        height: CELL_SIZE - 2,
        rx: 2,
        fill: (x + y) % 2 === 0 ? '#1e1e3a' : '#222244',
        stroke: '#2a2a4a',
        'stroke-width': 0.5,
      });
      rect.dataset.tileX = x;
      rect.dataset.tileY = y;
      layerTiles.appendChild(rect);
    }
  }
}

/**
 * Normalise a combat class string into a CSS-safe slug.
 * e.g. "Geometric Gunslinger" -> "geometric-gunslinger"
 */
function classSlug(raw) {
  return (raw || 'warrior').toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9\-]/g, '');
}

/**
 * Resolve a combat class to one of the four known silhouette symbol ids.
 * Falls back to "warrior" for custom/unknown classes.
 */
function resolveSilhouette(slug) {
  const known = ['warrior', 'mage', 'rogue', 'healer'];
  if (known.includes(slug)) return slug;
  // Heuristic: if slug contains a known base class, use it
  for (const k of known) {
    if (slug.includes(k)) return k;
  }
  return 'warrior'; // default fallback
}

// ===== Spritesheet helpers =====

/**
 * Build the spritesheet URL from a preset name.
 */
function spritesheetUrl(presetName) {
  return `/static/assets/spritesheets/${presetName}.png`;
}

/**
 * Set the spritesheet <image> offset to show a given frame.
 * @param {SVGImageElement} img - The <image> element inside the clipped <svg>
 * @param {number} col - Frame column (0-2)
 * @param {number} row - Direction row (SS_DIR.down/left/right/up)
 */
function setSpriteFrame(img, col, row) {
  img.setAttribute('x', -col * SS_FRAME_W);
  img.setAttribute('y', -row * SS_FRAME_H);
}

/**
 * Detect facing direction from position delta.
 */
function directionFromDelta(dx, dy) {
  if (dx === 0 && dy === 0) return null; // no movement
  if (Math.abs(dx) >= Math.abs(dy)) {
    return dx > 0 ? 'right' : 'left';
  }
  return dy > 0 ? 'down' : 'up';
}

/**
 * Play a 3-frame walk animation on a sprite's <image>.
 * Cycles frames 0→1→2 over ~300ms (matching CSS move transition).
 */
function playWalkAnimation(spriteG, direction) {
  const img = spriteG.querySelector('[data-role="ss-image"]');
  if (!img) return;

  const row = SS_DIR[direction] ?? SS_DIR.down;
  const frames = [0, 1, 2];
  const frameDuration = 100; // ms per frame

  let i = 0;
  // Clear any existing walk animation
  if (spriteG._walkTimer) clearInterval(spriteG._walkTimer);

  setSpriteFrame(img, frames[0], row);
  spriteG._walkTimer = setInterval(() => {
    i++;
    if (i >= frames.length) {
      clearInterval(spriteG._walkTimer);
      spriteG._walkTimer = null;
      // Return to idle frame facing this direction
      setSpriteFrame(img, SS_IDLE_COL, row);
      return;
    }
    setSpriteFrame(img, frames[i], row);
  }, frameDuration);
}

// ===== Sprite creation =====

/**
 * Create the visual element for a sprite — either spritesheet or silhouette.
 * Returns the element to append (either a nested <svg> or a <use>).
 */
function _createVisual(agentData) {
  if (agentData.sprite) {
    // Spritesheet mode: nested <svg> with clipped <image>
    const displayW = SPRITE_W;
    const displayH = SPRITE_W; // square — matches 32x32 source aspect ratio
    const offsetY = (SPRITE_H - displayH) / 2; // center vertically in SPRITE_H

    const nested = svgEl('svg', {
      x: 0,
      y: offsetY,
      width: displayW,
      height: displayH,
      viewBox: `0 0 ${SS_FRAME_W} ${SS_FRAME_H}`,
      overflow: 'hidden',
    });
    nested.dataset.role = 'ss-container';

    const img = svgEl('image', {
      href: spritesheetUrl(agentData.sprite),
      width: SS_SHEET_W,
      height: SS_SHEET_H,
      x: -SS_IDLE_COL * SS_FRAME_W,  // idle frame
      y: -SS_DIR.down * SS_FRAME_H,   // facing down by default
      'image-rendering': 'pixelated',
    });
    img.dataset.role = 'ss-image';
    nested.appendChild(img);

    return nested;
  }

  // Silhouette fallback
  const cls = classSlug(agentData.combat_class || 'warrior');
  const silhouette = resolveSilhouette(cls);
  return svgEl('use', {
    href: `#silhouette-${silhouette}`,
    width: SPRITE_W,
    height: SPRITE_H,
  });
}

/**
 * Create an agent sprite <g> group.
 */
function createSprite(agentData) {
  const rawCls = agentData.combat_class || 'warrior';
  const cls = classSlug(rawCls);
  const silhouette = resolveSilhouette(cls);
  const hasSheet = !!agentData.sprite;

  const g = svgEl('g', {
    'data-agent-id': agentData.id,
    'data-class': rawCls,
    'data-alive': agentData.is_alive ? 'true' : 'false',
    'data-active-turn': 'false',
  });
  if (hasSheet) {
    g.dataset.sprite = agentData.sprite;
    g.classList.add('sprite-group', 'sprite-sheet');
  } else {
    g.classList.add('sprite-group', `sprite-${silhouette}`);
  }

  // Store last known position for direction detection
  g._lastX = agentData.x;
  g._lastY = agentData.y;

  // Position
  const tx = agentData.x * CELL_SIZE + (CELL_SIZE - SPRITE_W) / 2;
  const ty = agentData.y * CELL_SIZE + (CELL_SIZE - SPRITE_H) / 2 - 2;
  g.setAttribute('transform', `translate(${tx}, ${ty})`);

  // Visual (spritesheet or silhouette)
  g.appendChild(_createVisual(agentData));

  // HP bar
  const hpBg = svgEl('rect', {
    class: 'hp-bar-bg',
    x: 0, y: SPRITE_H + 2,
    width: SPRITE_W, height: 4,
  });
  g.appendChild(hpBg);

  const hpPct = agentData.max_hp > 0 ? agentData.hp / agentData.max_hp : 0;
  const hpClass = hpPct > 0.6 ? 'hp-high' : hpPct > 0.3 ? 'hp-medium' : 'hp-low';
  const hpFill = svgEl('rect', {
    class: `hp-bar-fill ${hpClass}`,
    x: 0, y: SPRITE_H + 2,
    width: SPRITE_W * hpPct, height: 4,
  });
  hpFill.dataset.role = 'hp-fill';
  g.appendChild(hpFill);

  // Mana bar (thin line under HP)
  const manaPct = agentData.max_mana > 0 ? agentData.mana / agentData.max_mana : 0;
  const manaBar = svgEl('rect', {
    x: 0, y: SPRITE_H + 7,
    width: SPRITE_W * manaPct, height: 2,
    rx: 1,
    fill: '#4169e1',
    opacity: 0.8,
  });
  manaBar.dataset.role = 'mana-bar';
  g.appendChild(manaBar);

  // Name label
  const name = svgEl('text', {
    class: 'sprite-name',
    x: SPRITE_W / 2,
    y: SPRITE_H + 16,
  });
  name.textContent = agentData.name;
  g.appendChild(name);

  // Status overlay container
  const statusG = svgEl('g', { class: 'status-overlay' });
  statusG.dataset.role = 'status-container';
  g.appendChild(statusG);

  return g;
}

/**
 * Update an existing sprite's data.
 */
function updateSprite(spriteG, agentData) {
  // Detect movement direction before updating position
  const oldX = spriteG._lastX ?? agentData.x;
  const oldY = spriteG._lastY ?? agentData.y;
  const dx = agentData.x - oldX;
  const dy = agentData.y - oldY;
  spriteG._lastX = agentData.x;
  spriteG._lastY = agentData.y;

  // Position
  const tx = agentData.x * CELL_SIZE + (CELL_SIZE - SPRITE_W) / 2;
  const ty = agentData.y * CELL_SIZE + (CELL_SIZE - SPRITE_H) / 2 - 2;
  spriteG.setAttribute('transform', `translate(${tx}, ${ty})`);

  // Data attributes
  spriteG.dataset.alive = agentData.is_alive ? 'true' : 'false';

  // Spritesheet direction + walk animation
  if (spriteG.dataset.sprite) {
    const dir = directionFromDelta(dx, dy);
    if (dir) {
      playWalkAnimation(spriteG, dir);
    }
  }

  // HP bar
  const hpFill = spriteG.querySelector('[data-role="hp-fill"]');
  if (hpFill) {
    const hpPct = agentData.max_hp > 0 ? agentData.hp / agentData.max_hp : 0;
    hpFill.setAttribute('width', SPRITE_W * hpPct);
    hpFill.setAttribute('class', 'hp-bar-fill ' +
      (hpPct > 0.6 ? 'hp-high' : hpPct > 0.3 ? 'hp-medium' : 'hp-low'));
  }

  // Mana bar
  const manaBar = spriteG.querySelector('[data-role="mana-bar"]');
  if (manaBar) {
    const manaPct = agentData.max_mana > 0 ? agentData.mana / agentData.max_mana : 0;
    manaBar.setAttribute('width', SPRITE_W * manaPct);
  }

  // Status overlays
  const statusContainer = spriteG.querySelector('[data-role="status-container"]');
  if (statusContainer) {
    statusContainer.innerHTML = '';
    const effects = agentData.status_effects || [];
    effects.forEach((eff, i) => {
      const vis = getStatusVisual(eff.type);
      const icon = svgEl('text', {
        class: `status-icon ${vis.animation}`,
        x: 4 + i * 10,
        y: -4,
        fill: vis.color,
      });
      icon.textContent = vis.icon;
      statusContainer.appendChild(icon);
    });
  }
}

/**
 * Spawn a floating damage number.
 */
function spawnDamageNumber(layerEffects, x, y, text, cssClass) {
  const el = svgEl('text', {
    class: `damage-number ${cssClass}`,
    x: x,
    y: y,
  });
  el.textContent = text;
  layerEffects.appendChild(el);

  // Remove after animation
  setTimeout(() => {
    if (el.parentNode) el.parentNode.removeChild(el);
  }, 1000);
}

/**
 * Determine lunge direction from attacker to target.
 */
function getLungeDirection(ax, ay, tx, ty) {
  const dx = tx - ax;
  const dy = ty - ay;
  if (Math.abs(dx) >= Math.abs(dy)) {
    return dx > 0 ? 'anim-lunge-right' : 'anim-lunge-left';
  }
  return dy > 0 ? 'anim-lunge-down' : 'anim-lunge-up';
}
