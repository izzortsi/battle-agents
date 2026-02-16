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
 * Draw a rune glyph from RUNE_GLYPHS onto a tile.
 * Coordinates in the glyph definitions are normalised 0-1; this function
 * scales them into the cell's pixel space with an inset margin.
 */
function _drawRuneGlyph(layer, tileX, tileY, glyphIdx, color) {
  const glyph = RUNE_GLYPHS[glyphIdx % RUNE_GLYPHS.length];
  const inset = 8;
  const ox = tileX * CELL_SIZE + inset;
  const oy = tileY * CELL_SIZE + inset;
  const sz = CELL_SIZE - inset * 2;

  // Paths (filled outlines)
  for (const d of (glyph.paths || [])) {
    // Scale normalised coords: replace numeric values
    const scaled = d.replace(/(\d+\.\d+)/g, (_, v) => '___' + v);
    // We need to manually transform — parse M/L/Z tokens
    const tokens = d.match(/[MLZ]|[\d.]+/g) || [];
    let sd = '';
    let isX = true;
    for (const tok of tokens) {
      if (tok === 'M' || tok === 'L' || tok === 'Z') {
        sd += tok + ' ';
        isX = true;
      } else {
        const n = parseFloat(tok);
        sd += (isX ? (ox + n * sz) : (oy + n * sz)).toFixed(1) + ' ';
        isX = !isX;
      }
    }
    layer.appendChild(svgEl('path', {
      d: sd.trim(),
      fill: 'none', stroke: color,
      'stroke-width': 1.5, opacity: 0.55,
      'stroke-linejoin': 'round',
      class: 'rune-glow',
      'pointer-events': 'none',
    }));
  }

  // Circles
  for (const c of (glyph.circles || [])) {
    layer.appendChild(svgEl('circle', {
      cx: ox + c.cx * sz,
      cy: oy + c.cy * sz,
      r: c.r * sz,
      fill: 'none', stroke: color,
      'stroke-width': 1.2, opacity: 0.50,
      class: 'rune-glow',
      'pointer-events': 'none',
    }));
  }

  // Lines
  for (const l of (glyph.lines || [])) {
    layer.appendChild(svgEl('line', {
      x1: ox + l.x1 * sz, y1: oy + l.y1 * sz,
      x2: ox + l.x2 * sz, y2: oy + l.y2 * sz,
      stroke: color,
      'stroke-width': 1.0, opacity: 0.45,
      class: 'rune-glow',
      'pointer-events': 'none',
    }));
  }
}

/**
 * Create tile grid rects.
 * @param {SVGGElement} layerTiles - The SVG <g> to append tile elements to.
 * @param {number} gridW - Grid width in cells.
 * @param {number} gridH - Grid height in cells.
 * @param {string[][]|null} tiles - Row-major tile type array (tiles[y][x]).
 *        Each value is a tile type string (e.g. "floor", "stone", "rune").
 *        Falls back to all-floor if null/undefined.
 */
function createGridTiles(layerTiles, gridW, gridH, tiles) {
  layerTiles.innerHTML = '';
  for (let y = 0; y < gridH; y++) {
    for (let x = 0; x < gridW; x++) {
      const tileType = (tiles && tiles[y] && tiles[y][x]) || 'floor';
      const style = TILE_COLORS[tileType] || TILE_COLORS.floor;
      const isEven = (x + y) % 2 === 0;

      const attrs = {
        x: x * CELL_SIZE + 1,
        y: y * CELL_SIZE + 1,
        width: CELL_SIZE - 2,
        height: CELL_SIZE - 2,
        rx: 2,
        fill: isEven ? style.even : style.odd,
        stroke: style.stroke,
        'stroke-width': style.strokeWidth || 0.5,
      };
      if (style.dashArray) {
        attrs['stroke-dasharray'] = style.dashArray;
      }

      const rect = svgEl('rect', attrs);
      rect.dataset.tileX = x;
      rect.dataset.tileY = y;
      layerTiles.appendChild(rect);

      // Inner detail elements for special tile types
      if (style.detail) {
        const cx = x * CELL_SIZE + CELL_SIZE / 2;
        const cy = y * CELL_SIZE + CELL_SIZE / 2;
        const shape = style.detailShape || 'rect';

        if (shape === 'circle') {
          // Pillar: circular column viewed top-down
          const r = (CELL_SIZE - 2) / 2 - 8;
          layerTiles.appendChild(svgEl('circle', {
            cx: cx, cy: cy, r: r,
            fill: style.detail, opacity: 0.7,
            'pointer-events': 'none',
          }));
          // Inner highlight for 3D convexity
          layerTiles.appendChild(svgEl('circle', {
            cx: cx - 3, cy: cy - 3, r: r * 0.45,
            fill: '#8878a0', opacity: 0.25,
            'pointer-events': 'none',
          }));

        } else if (shape === 'speckle') {
          // Gravel: scattered dots and small irregular shapes for gritty texture
          const offsets = [[-8,-6],[6,-8],[0,4],[-5,7],[8,2],[-3,-2],[5,-3],[-7,3],[7,-4],[2,-7],[-4,5]];
          for (const [dx, dy] of offsets) {
            layerTiles.appendChild(svgEl('circle', {
              cx: cx + dx, cy: cy + dy,
              r: 1.5 + ((x * 7 + y * 3 + dx) % 3) * 0.6,
              fill: style.detail, opacity: 0.50,
              'pointer-events': 'none',
            }));
          }
          // A few larger pebble shapes for variety
          layerTiles.appendChild(svgEl('ellipse', {
            cx: cx - 4, cy: cy + 2, rx: 3, ry: 2,
            fill: style.detail, opacity: 0.35,
            'pointer-events': 'none',
          }));
          layerTiles.appendChild(svgEl('ellipse', {
            cx: cx + 5, cy: cy - 5, rx: 2.5, ry: 1.5,
            fill: style.detail, opacity: 0.30,
            'pointer-events': 'none',
          }));

        } else if (shape === 'cracks') {
          // Cracked: bold jagged crack lines across the tile
          const tl = x * CELL_SIZE;
          const tt = y * CELL_SIZE;
          const s = CELL_SIZE;
          // Main diagonal crack
          layerTiles.appendChild(svgEl('path', {
            d: `M${tl + s*0.15},${tt + s*0.1} L${tl + s*0.35},${tt + s*0.38} L${tl + s*0.28},${tt + s*0.55} L${tl + s*0.52},${tt + s*0.72} L${tl + s*0.8},${tt + s*0.88}`,
            fill: 'none', stroke: style.detail,
            'stroke-width': 1.8, opacity: 0.55,
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
            'pointer-events': 'none',
          }));
          // Branch crack
          layerTiles.appendChild(svgEl('path', {
            d: `M${tl + s*0.35},${tt + s*0.38} L${tl + s*0.58},${tt + s*0.28} L${tl + s*0.72},${tt + s*0.38}`,
            fill: 'none', stroke: style.detail,
            'stroke-width': 1.3, opacity: 0.45,
            'stroke-linecap': 'round',
            'stroke-linejoin': 'round',
            'pointer-events': 'none',
          }));
          // Secondary hairline crack
          layerTiles.appendChild(svgEl('path', {
            d: `M${tl + s*0.28},${tt + s*0.55} L${tl + s*0.15},${tt + s*0.7} L${tl + s*0.22},${tt + s*0.85}`,
            fill: 'none', stroke: style.detail,
            'stroke-width': 0.9, opacity: 0.35,
            'stroke-linecap': 'round',
            'pointer-events': 'none',
          }));

        } else if (shape === 'rune') {
          // Rune glyph — pick a design based on tile position
          const glyphIdx = (x * 3 + y * 7) % RUNE_GLYPHS.length;
          _drawRuneGlyph(layerTiles, x, y, glyphIdx, style.detail);

        } else {
          // Default: rectangular detail (furniture tabletop)
          const inset = 10;
          layerTiles.appendChild(svgEl('rect', {
            x: x * CELL_SIZE + inset,
            y: y * CELL_SIZE + inset,
            width: CELL_SIZE - inset * 2,
            height: CELL_SIZE - inset * 2,
            rx: 4,
            fill: style.detail, opacity: 0.6,
            'pointer-events': 'none',
          }));
        }
      }
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
  return `/static/assets/spritesheets/${presetName}.png?v=${ASSET_VERSION}`;
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

  // Emoji bubble (thinking / talking indicator — hidden by default)
  const fo = svgEl('foreignObject', {
    x: 0,
    y: -20,
    width: SPRITE_W,
    height: 22,
    overflow: 'visible',
  });
  fo.setAttribute('data-role', 'emoji-bubble');
  fo.setAttribute('class', 'sprite-emoji-fo');
  const emojiDiv = document.createElementNS('http://www.w3.org/1999/xhtml', 'div');
  emojiDiv.setAttribute('class', 'sprite-emoji');
  emojiDiv.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml');
  fo.appendChild(emojiDiv);
  g.appendChild(fo);

  return g;
}

/**
 * Show or clear the emoji bubble above a sprite.
 * @param {SVGGElement} spriteG — the sprite <g> element
 * @param {string} emoji — emoji character to show, or '' to clear
 */
function setSpriteEmoji(spriteG, emoji) {
  const fo = spriteG.querySelector('foreignObject[data-role="emoji-bubble"]');
  if (!fo) return;
  const div = fo.firstElementChild;
  if (!div) return;
  div.textContent = emoji || '';
  if (emoji) {
    fo.style.display = '';
  } else {
    fo.style.display = 'none';
  }
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

// ===== Grid decorations =====

/**
 * Draw a large decorative rune on the highlights layer.
 * Uses a RUNE_GLYPHS design scaled to span multiple cells.
 */
function _drawLargeRune(layer, cx, cy, size, glyphIdx, color, baseOpacity) {
  const glyph = RUNE_GLYPHS[glyphIdx % RUNE_GLYPHS.length];
  const ox = cx - size / 2;
  const oy = cy - size / 2;

  // Outer containment circle
  layer.appendChild(svgEl('circle', {
    cx: cx, cy: cy, r: size / 2,
    fill: 'none', stroke: color,
    'stroke-width': 1.5, opacity: baseOpacity,
    class: 'rune-glow',
    'pointer-events': 'none',
  }));

  // Glyph paths
  for (const d of (glyph.paths || [])) {
    const tokens = d.match(/[MLZ]|[\d.]+/g) || [];
    let sd = '';
    let isX = true;
    for (const tok of tokens) {
      if (tok === 'M' || tok === 'L' || tok === 'Z') {
        sd += tok + ' ';
        isX = true;
      } else {
        const n = parseFloat(tok);
        sd += (isX ? (ox + n * size) : (oy + n * size)).toFixed(1) + ' ';
        isX = !isX;
      }
    }
    layer.appendChild(svgEl('path', {
      d: sd.trim(),
      fill: 'none', stroke: color,
      'stroke-width': 1.5, opacity: baseOpacity * 0.9,
      'stroke-linejoin': 'round',
      class: 'rune-glow',
      'pointer-events': 'none',
    }));
  }

  // Glyph circles
  for (const c of (glyph.circles || [])) {
    layer.appendChild(svgEl('circle', {
      cx: ox + c.cx * size,
      cy: oy + c.cy * size,
      r: c.r * size,
      fill: 'none', stroke: color,
      'stroke-width': 1.2, opacity: baseOpacity * 0.8,
      class: 'rune-glow',
      'pointer-events': 'none',
    }));
  }

  // Glyph lines
  for (const l of (glyph.lines || [])) {
    layer.appendChild(svgEl('line', {
      x1: ox + l.x1 * size, y1: oy + l.y1 * size,
      x2: ox + l.x2 * size, y2: oy + l.y2 * size,
      stroke: color,
      'stroke-width': 1.0, opacity: baseOpacity * 0.7,
      class: 'rune-glow',
      'pointer-events': 'none',
    }));
  }
}

/**
 * Add ambient decorations to the grid: pillar shadows, scattered rune
 * glyphs, and an edge vignette for depth.  Appended to the highlights
 * layer (between tiles and agents).
 *
 * @param {SVGGElement} layerHighlights - The #layer-highlights <g>.
 * @param {number} gridW - Grid width in cells.
 * @param {number} gridH - Grid height in cells.
 * @param {string[][]|null} tiles - Row-major tile data.
 * @param {SVGElement} svgRoot - The top-level <svg> for defs.
 */
function createGridDecorations(layerHighlights, gridW, gridH, tiles, svgRoot) {
  layerHighlights.innerHTML = '';
  const totalW = gridW * CELL_SIZE;
  const totalH = gridH * CELL_SIZE;

  // --- Pillar shadows: dark ellipses offset to bottom-right ---
  if (tiles) {
    for (let y = 0; y < gridH; y++) {
      for (let x = 0; x < gridW; x++) {
        if (tiles[y] && tiles[y][x] === 'pillar') {
          const cx = x * CELL_SIZE + CELL_SIZE / 2 + 4;
          const cy = y * CELL_SIZE + CELL_SIZE / 2 + 6;
          layerHighlights.appendChild(svgEl('ellipse', {
            cx: cx, cy: cy,
            rx: (CELL_SIZE - 2) / 2 - 4,
            ry: (CELL_SIZE - 2) / 2 - 8,
            fill: '#000', opacity: 0.18,
            'pointer-events': 'none',
          }));
        }
      }
    }
  }

  // --- Large rune glyphs (arena only — skip for tavern/social maps) ---
  // Detect arena by checking for pillar or rune tiles
  let isArena = false;
  if (tiles) {
    for (let y = 0; y < gridH && !isArena; y++) {
      for (let x = 0; x < gridW && !isArena; x++) {
        const t = tiles[y] && tiles[y][x];
        if (t === 'pillar' || t === 'rune' || t === 'cracked') isArena = true;
      }
    }
  }

  if (!isArena) {
    // Skip rune decorations for non-arena maps (tavern, etc.)
    // Still apply vignette below.
  } else {
  // 4 corner runes (large, each a different glyph design)
  const cornerInset = CELL_SIZE * 1.0;
  const cornerSize = CELL_SIZE * 1.5;
  const cornerPositions = [
    [cornerInset,             cornerInset,              0],
    [totalW - cornerInset,    cornerInset,              1],
    [cornerInset,             totalH - cornerInset,     2],
    [totalW - cornerInset,    totalH - cornerInset,     3],
  ];
  for (const [cx, cy, gIdx] of cornerPositions) {
    _drawLargeRune(layerHighlights, cx, cy, cornerSize, gIdx, '#9b8aff', 0.35);
  }

  // Center rune (largest, most prominent)
  const centerCx = totalW / 2;
  const centerCy = totalH / 2;
  _drawLargeRune(layerHighlights, centerCx, centerCy, CELL_SIZE * 2.0, 0, '#a090ff', 0.30);

  // Mid-edge runes (smaller, between center and corners)
  if (gridW >= 8 && gridH >= 6) {
    const midRuneSize = CELL_SIZE * 1.0;
    const midRunePositions = [
      [totalW / 2,  CELL_SIZE * 1.0,           1],  // top center
      [totalW / 2,  totalH - CELL_SIZE * 1.0,  3],  // bottom center
      [CELL_SIZE * 1.0,  totalH / 2,           2],  // left center
      [totalW - CELL_SIZE * 1.0, totalH / 2,   0],  // right center
    ];
    for (const [cx, cy, gIdx] of midRunePositions) {
      _drawLargeRune(layerHighlights, cx, cy, midRuneSize, gIdx, '#8878ee', 0.28);
    }
  }
  } // end isArena rune block

  // --- Edge vignette: radial gradient mask for depth ---
  const defsEl = svgRoot.querySelector('#svg-defs');
  if (defsEl) {
    if (!defsEl.querySelector('#vignette-gradient')) {
      const radial = svgEl('radialGradient', { id: 'vignette-gradient' });
      radial.appendChild(svgEl('stop', { offset: '55%', 'stop-color': '#000', 'stop-opacity': '0' }));
      radial.appendChild(svgEl('stop', { offset: '100%', 'stop-color': '#000', 'stop-opacity': '0.35' }));
      defsEl.appendChild(radial);
    }

    layerHighlights.appendChild(svgEl('rect', {
      x: 0, y: 0,
      width: totalW, height: totalH,
      fill: 'url(#vignette-gradient)',
      'pointer-events': 'none',
    }));
  }
}
