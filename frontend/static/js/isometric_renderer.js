/**
 * isometric_renderer.js — Canvas-based isometric renderer (no Phaser yet).
 *
 * Goal: Replace SVG grid rendering without touching the refined DOM panels.
 * This renderer consumes authoritative backend state:
 * - state.grid.tiles (tiles[y][x])
 * - state.grid.heights (heights[y][x])
 * - state.agents[*].x/y/z + sprite preset
 * - state.awaitingPlayer.legalActions + state.playerMode (for highlights)
 *
 * Later: evolve into Phaser, but keep this API surface so renderer.js can stay stable.
 */

(function () {
  const DPR = () => Math.max(1, Math.floor(window.devicePixelRatio || 1));

  function tileTypeAt(grid, x, y) {
    const t = grid && grid.tiles && grid.tiles[y] && grid.tiles[y][x];
    return t || 'floor';
  }

  function heightAt(grid, x, y) {
    const h = grid && grid.heights && grid.heights[y] && grid.heights[y][x];
    return (typeof h === 'number') ? h : 0;
  }

  function getTileStyle(tileType, parity) {
    const base =
      (typeof TILE_COLORS !== 'undefined' && TILE_COLORS[tileType]) ||
      (typeof TILE_COLORS !== 'undefined' && TILE_COLORS.floor);

    if (!base) {
      return {
        fill: parity ? '#222244' : '#1e1e3a',
        stroke: '#2a2a4a',
      };
    }

    const fill = parity ? base.even : base.odd;
    const stroke = base.stroke || '#2a2a4a';
    return { fill, stroke };
  }

  function hexToRgba(hex, a) {
    if (!hex || hex[0] !== '#' || hex.length !== 7) return `rgba(0,0,0,${a})`;
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r},${g},${b},${a})`;
  }

  class SpriteCache {
    constructor() {
      this._images = new Map();
    }
    get(preset) {
      if (!preset) return null;
      if (this._images.has(preset)) return this._images.get(preset);

      const img = new Image();
      const v = (typeof ASSET_VERSION !== 'undefined') ? ASSET_VERSION : 1;
      img.src = `/static/assets/spritesheets/${preset}.png?v=${v}`;
      this._images.set(preset, img);
      return img;
    }
  }

  class IsometricRenderer {
    constructor(canvas, state) {
      this.canvas = canvas;
      this.state = state;
      this.ctx = canvas.getContext('2d');
      this._spriteCache = new SpriteCache();

      const base = (typeof CELL_SIZE !== 'undefined') ? CELL_SIZE : 52;
      this.tileW = Math.round(base * 1.35);
      this.tileH = Math.round(this.tileW * 0.5);
      this.heightStep = 10;

      this._lastSizeKey = '';
      this._hitTiles = [];
      this._hitUnits = [];

      // Auto-redraw when the canvas is resized by the layout/resizer handles.
      this._resizeQueued = false;
      if (window.ResizeObserver) {
        const ro = new ResizeObserver(() => {
          if (this._resizeQueued) return;
          this._resizeQueued = true;
          requestAnimationFrame(() => {
            this._resizeQueued = false;
            this.renderFull();
          });
        });
        ro.observe(this.canvas);
        this._resizeObserver = ro;
      }
    }

    setState(state) {
      this.state = state;
    }

    resizeToFit() {
      const dpr = DPR();
      const w = Math.max(1, this.canvas.clientWidth);
      const h = Math.max(1, this.canvas.clientHeight);
      const key = `${w}x${h}@${dpr}`;
      if (key === this._lastSizeKey) return;

      this._lastSizeKey = key;
      this.canvas.width = w * dpr;
      this.canvas.height = h * dpr;
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    gridToScreen(x, y, z, originX, originY) {
      const sx = originX + (x - y) * (this.tileW / 2);
      const sy = originY + (x + y) * (this.tileH / 2) - z * this.heightStep;
      return { sx, sy };
    }

    _computeOrigin(grid) {
      const w = this.canvas.clientWidth;
      const h = this.canvas.clientHeight;
      const gw = grid.width || 12;
      const gh = grid.height || 10;

      const footprintH = (gw + gh) * (this.tileH / 2);
      const originX = Math.round(w / 2);
      const originY = Math.round((h - footprintH) / 2 + 24);
      return { originX, originY };
    }

    _pointInDiamond(px, py, sx, sy) {
      const cx = sx + this.tileW / 2;
      const cy = sy + this.tileH / 2;
      const dx = Math.abs(px - cx) / (this.tileW / 2);
      const dy = Math.abs(py - cy) / (this.tileH / 2);
      return (dx + dy) <= 1.0;
    }

    pickAt(px, py) {
      // units first (front-to-back)
      for (let i = this._hitUnits.length - 1; i >= 0; i--) {
        const u = this._hitUnits[i];
        const dx = px - u.cx;
        const dy = py - u.cy;
        if (dx * dx + dy * dy <= u.r * u.r) {
          return { kind: 'unit', agentId: u.agentId };
        }
      }

      // then tiles (front-to-back)
      for (let i = this._hitTiles.length - 1; i >= 0; i--) {
        const t = this._hitTiles[i];
        if (this._pointInDiamond(px, py, t.sx, t.sy)) {
          return { kind: 'tile', tile: t.tileKey, x: t.x, y: t.y };
        }
      }

      return null;
    }

    renderFull() {
      if (!this.ctx || !this.state || !this.state.grid) return;

      this.resizeToFit();

      const ctx = this.ctx;
      const grid = this.state.grid;
      const { originX, originY } = this._computeOrigin(grid);

      ctx.clearRect(0, 0, this.canvas.clientWidth, this.canvas.clientHeight);
      ctx.fillStyle = '#111428';
      ctx.fillRect(0, 0, this.canvas.clientWidth, this.canvas.clientHeight);

      const gw = grid.width || 12;
      const gh = grid.height || 10;

      const order = [];
      for (let y = 0; y < gh; y++) {
        for (let x = 0; x < gw; x++) {
          order.push({ x, y, k: x + y });
        }
      }
      order.sort((a, b) => (a.k - b.k) || (a.y - b.y) || (a.x - b.x));

      // Highlights from backend legal actions (authoritative)
      const awaiting = this.state.awaitingPlayer;
      const legal = awaiting ? (awaiting.legalActions || {}) : null;
      // Committed mode takes priority; fall back to hover preview when idle.
      const mode = (this.state.playerMode && this.state.playerMode !== 'idle')
        ? this.state.playerMode
        : (this.state.hoverMode || 'idle');
      const moveSet = new Set((legal && legal.valid_moves) || []);
      const attackSet = new Set(((legal && legal.attack_targets) || []).map(t => t.agent_id));

      const awaitingAgentId = awaiting ? awaiting.agentId : null;
      const awaitingAgent = awaitingAgentId ? (this.state.agents || {})[awaitingAgentId] : null;

      const buildRangeTileSet = (range) => {
        const set = new Set();
        if (!awaitingAgent || range == null) return set;
        const ax = awaitingAgent.x;
        const ay = awaitingAgent.y;
        if (typeof ax !== 'number' || typeof ay !== 'number') return set;

        for (let dx = -range; dx <= range; dx++) {
          for (let dy = -range; dy <= range; dy++) {
            if (Math.abs(dx) + Math.abs(dy) > range) continue;
            const nx = ax + dx;
            const ny = ay + dy;
            if (nx < 0 || ny < 0 || nx >= gw || ny >= gh) continue;
            set.add(`${nx}_${ny}`);
          }
        }
        return set;
      };

      // Ability target set — resolved from selected ability or hover preview
      const abilityTargetSet = new Set();
      let selectedAbility = null;
      if (mode === 'ability') {
        const abilityName = this.state.selectedAbilityName || this.state.hoverAbilityName;
        if (abilityName) {
          const legalAbs = (legal && legal.abilities) || [];
          selectedAbility = legalAbs.find(ab => ab.name === abilityName);
          if (selectedAbility) for (const t of (selectedAbility.targets || [])) abilityTargetSet.add(t.agent_id);
        }
      }

      // Tile-position sets: resolve agent_id → "x_y" tile key for target tile highlights.
      // We look up state.agents[id].x/y so the highlight lands on the correct diamond.
      const _ags = this.state.agents || {};
      const _agTile = (id) => { const a = _ags[id]; return (a && a.is_alive !== false) ? `${a.x}_${a.y}` : null; };

      const attackTileSet = new Set();
      if (mode === 'attack') {
        const attackRange = legal ? legal.attack_range : null;
        for (const t of buildRangeTileSet(attackRange)) attackTileSet.add(t);
      }
      for (const id of attackSet) { const tk = _agTile(id); if (tk) attackTileSet.add(tk); }

      const abilityTileSet = new Set();
      if (mode === 'ability' && selectedAbility) {
        for (const t of buildRangeTileSet(selectedAbility.range)) abilityTileSet.add(t);
      }
      for (const id of abilityTargetSet) { const tk = _agTile(id); if (tk) abilityTileSet.add(tk); }

      const chatTileSet = new Set();
      if (mode === 'chat') {
        const chatRange = legal ? legal.chat_range : null;
        for (const t of buildRangeTileSet(chatRange)) chatTileSet.add(t);
      }
      for (const t of ((legal && legal.chat_targets) || [])) {
        if (t && t.agent_id) { const tk = _agTile(t.agent_id); if (tk) chatTileSet.add(tk); }
      }

      this._hitTiles = [];
      this._hitUnits = [];

      for (const cell of order) {
        const x = cell.x, y = cell.y;
        const z = heightAt(grid, x, y);
        const { sx, sy } = this.gridToScreen(x, y, z, originX, originY);
        const tileKey = `${x}_${y}`;

        this._hitTiles.push({ sx, sy, tileKey, x, y });

        const tileType = tileTypeAt(grid, x, y);
        const parity = ((x + y) % 2) === 0;
        const style = getTileStyle(tileType, parity);

        // Side faces
        if (z > 0) {
          const baseSy = sy + z * this.heightStep;
          ctx.fillStyle = hexToRgba(style.fill, 0.28);

          ctx.beginPath();
          ctx.moveTo(sx, baseSy + this.tileH / 2);
          ctx.lineTo(sx + this.tileW / 2, baseSy + this.tileH);
          ctx.lineTo(sx + this.tileW / 2, sy + this.tileH);
          ctx.lineTo(sx, sy + this.tileH / 2);
          ctx.closePath();
          ctx.fill();

          ctx.beginPath();
          ctx.moveTo(sx + this.tileW / 2, baseSy + this.tileH);
          ctx.lineTo(sx + this.tileW, baseSy + this.tileH / 2);
          ctx.lineTo(sx + this.tileW, sy + this.tileH / 2);
          ctx.lineTo(sx + this.tileW / 2, sy + this.tileH);
          ctx.closePath();
          ctx.fill();
        }

        // Top diamond
        ctx.beginPath();
        ctx.moveTo(sx + this.tileW / 2, sy);
        ctx.lineTo(sx + this.tileW, sy + this.tileH / 2);
        ctx.lineTo(sx + this.tileW / 2, sy + this.tileH);
        ctx.lineTo(sx, sy + this.tileH / 2);
        ctx.closePath();

        ctx.fillStyle = style.fill;
        ctx.fill();

        ctx.strokeStyle = hexToRgba(style.stroke, 0.35);
        ctx.lineWidth = 1;
        ctx.stroke();

        // Move target tiles — green
        if (mode === 'move' && moveSet.has(tileKey)) {
          ctx.fillStyle = 'rgba(60,179,113,0.20)';
          ctx.fill();
          ctx.strokeStyle = 'rgba(60,179,113,0.55)';
          ctx.stroke();
        }

        // Attack target tiles — red (matches unit ring color)
        if (mode === 'attack' && attackTileSet.has(tileKey)) {
          ctx.fillStyle = 'rgba(233,69,96,0.18)';
          ctx.fill();
          ctx.strokeStyle = 'rgba(233,69,96,0.55)';
          ctx.stroke();
        }

        // Ability target tiles — purple (matches unit ring color)
        if (mode === 'ability' && abilityTileSet.has(tileKey)) {
          ctx.fillStyle = 'rgba(162,155,254,0.18)';
          ctx.fill();
          ctx.strokeStyle = 'rgba(162,155,254,0.55)';
          ctx.stroke();
        }

        // Chat target tiles — gold (wired for when chat mode button is added)
        if (mode === 'chat' && chatTileSet.has(tileKey)) {
          ctx.fillStyle = 'rgba(218,165,32,0.15)';
          ctx.fill();
          ctx.strokeStyle = 'rgba(218,165,32,0.45)';
          ctx.stroke();
        }
      }

      // Units
      const units = Object.values(this.state.agents || {});
      units.sort((a, b) => ((a.x + a.y) - (b.x + b.y)) || (a.y - b.y) || (a.x - b.x));

      for (const u of units) {
        if (!u || u.is_alive === false) continue;

        const z = (typeof u.z === 'number') ? u.z : heightAt(grid, u.x, u.y);
        const { sx, sy } = this.gridToScreen(u.x, u.y, z, originX, originY);

        const cx = sx + this.tileW / 2;
        const cy = sy + this.tileH / 2;

        // Clickable hit circle near the sprite torso
        this._hitUnits.push({ agentId: u.id, cx: cx, cy: cy - 20, r: 18 });

        // Attack highlight: red ring on valid targets
        if (mode === 'attack' && attackSet.has(u.id)) {
          ctx.save();
          ctx.strokeStyle = 'rgba(233,69,96,0.85)'; // accent-red
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.ellipse(cx, cy - 10, 18, 8, 0, 0, Math.PI * 2);
          ctx.stroke();
          ctx.restore();
        }

        // Ability target highlight: purple ring
        if (mode === 'ability' && abilityTargetSet.has(u.id)) {
          ctx.save();
          ctx.strokeStyle = 'rgba(162,155,254,0.90)'; // accent-purple
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.ellipse(cx, cy - 10, 20, 9, 0, 0, Math.PI * 2);
          ctx.stroke();
          ctx.restore();
        }

        // Sprite (idle)
        if (u.sprite) {
          const img = this._spriteCache.get(u.sprite);
          const frameW = (typeof SS_FRAME_W !== 'undefined') ? SS_FRAME_W : 32;
          const frameH = (typeof SS_FRAME_H !== 'undefined') ? SS_FRAME_H : 32;
          const idleCol = (typeof SS_IDLE_COL !== 'undefined') ? SS_IDLE_COL : 1;
          const downRow = (typeof SS_DIR !== 'undefined' && SS_DIR.down != null) ? SS_DIR.down : 0;

          const srcX = idleCol * frameW;
          const srcY = downRow * frameH;

          const drawW = 40;
          const drawH = 40;
          ctx.drawImage(img, srcX, srcY, frameW, frameH, cx - drawW / 2, cy - drawH - 10, drawW, drawH);
        } else {
          ctx.fillStyle = hexToRgba('#daa520', 0.85);
          ctx.beginPath();
          ctx.arc(cx, cy - 18, 10, 0, Math.PI * 2);
          ctx.fill();
        }

        // Active unit halo
        if (this.state && this.state.activeAgent && u.id === this.state.activeAgent) {
          ctx.save();
          ctx.strokeStyle = 'rgba(218,165,32,0.85)';
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.ellipse(cx, cy - 6, 18, 8, 0, 0, Math.PI * 2);
          ctx.stroke();
          ctx.restore();
        }

        // Name
        ctx.font = '11px Segoe UI, Consolas, monospace';
        ctx.fillStyle = 'rgba(224,224,224,0.85)';
        ctx.textAlign = 'center';
        ctx.fillText(u.name || u.id || '?', cx, cy + 22);
      }
    }
  }

  window.IsometricRenderer = IsometricRenderer;
})();
