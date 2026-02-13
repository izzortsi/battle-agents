/**
 * sprites.js — SVG sprite factory. Creates and updates agent sprites from data.
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
 * Create an agent sprite <g> group.
 */
function createSprite(agentData) {
  const cls = agentData.combat_class || 'warrior';
  const g = svgEl('g', {
    'data-agent-id': agentData.id,
    'data-class': cls,
    'data-alive': agentData.is_alive ? 'true' : 'false',
    'data-active-turn': 'false',
  });
  g.classList.add('sprite-group', `sprite-${cls}`);

  // Position
  const tx = agentData.x * CELL_SIZE + (CELL_SIZE - SPRITE_W) / 2;
  const ty = agentData.y * CELL_SIZE + (CELL_SIZE - SPRITE_H) / 2 - 2;
  g.setAttribute('transform', `translate(${tx}, ${ty})`);

  // Silhouette via <use>
  const use = svgEl('use', {
    href: `#silhouette-${cls}`,
    width: SPRITE_W,
    height: SPRITE_H,
  });
  g.appendChild(use);

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
  // Position
  const tx = agentData.x * CELL_SIZE + (CELL_SIZE - SPRITE_W) / 2;
  const ty = agentData.y * CELL_SIZE + (CELL_SIZE - SPRITE_H) / 2 - 2;
  spriteG.setAttribute('transform', `translate(${tx}, ${ty})`);

  // Data attributes
  spriteG.dataset.alive = agentData.is_alive ? 'true' : 'false';

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
