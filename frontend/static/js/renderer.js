/**
 * renderer.js — DOM update orchestration. Calls sub-renderers on state change.
 */

class Renderer {
  constructor(state) {
    this.state = state;
    this._sprites = {};   // agent_id -> <g> element
    this._gridCreated = false;

    this.svg = document.getElementById('battle-grid');
    this.layerTiles = document.getElementById('layer-tiles');
    this.layerHighlights = document.getElementById('layer-highlights');
    this.layerSocialLines = document.getElementById('layer-social-lines');
    this.layerAgents = document.getElementById('layer-agents');
    this.layerEffects = document.getElementById('layer-effects');
  }

  onStateChange(changeType, detail) {
    switch (changeType) {
      case 'snapshot':
        this._renderFull();
        break;
      case 'phase':
        this._updateHeader();
        break;
      case 'turn_start':
        this._updateActiveTurn();
        this._updateHeader();
        renderCards(this.state);
        break;
      case 'action':
        this._updateAgents();
        this._playActionAnimation(detail);
        renderLog(this.state);
        renderCards(this.state);
        renderCharacterSheet(this.state);
        break;
      case 'dialogue':
        renderDialogue(this.state);
        break;
      case 'cognitive':
        renderCognitive(this.state);
        break;
      case 'death':
        this._playDeathAnimation(detail);
        this._updateAgents();
        renderCards(this.state);
        renderLog(this.state);
        break;
      case 'victory':
        this._updateHeader();
        renderLog(this.state);
        break;
      case 'lore':
        renderLore(this.state);
        break;
      case 'commentary':
        renderCommentaryEntry(this.state);
        break;
      case 'social_update':
        renderSocial(this.state);
        break;
      case 'select':
        renderCards(this.state);
        renderCharacterSheet(this.state);
        renderCognitive(this.state);
        renderSocial(this.state);
        break;
    }
  }

  _renderFull() {
    this._createGrid();
    this._createSprites();
    this._updateHeader();
    renderLore(this.state);
    this._updateActiveTurn();
    renderCards(this.state);
    renderCharacterSheet(this.state);
    renderSocial(this.state);
    renderCognitive(this.state);
    renderLog(this.state);
    renderDialogue(this.state);
  }

  _createGrid() {
    const { width, height, tiles } = this.state.grid;

    // Skip rebuild if dimensions and tile data haven't changed
    if (this._gridCreated
        && this._gridW === width
        && this._gridH === height
        && this._gridTiles === tiles) {
      return;
    }

    // Size SVG — use viewBox for coordinate space, CSS for responsive fill
    const svgW = width * CELL_SIZE;
    const svgH = height * CELL_SIZE + 20; // extra for labels
    this.svg.removeAttribute('width');
    this.svg.removeAttribute('height');
    this.svg.setAttribute('viewBox', `0 0 ${svgW} ${svgH}`);

    // Inject defs
    injectDefs(this.svg);

    // Create tiles (pass tile type data for per-tile styling)
    createGridTiles(this.layerTiles, width, height, tiles || null);

    this._gridW = width;
    this._gridH = height;
    this._gridTiles = tiles;
    this._gridCreated = true;
  }

  _createSprites() {
    this.layerAgents.innerHTML = '';
    this._sprites = {};

    for (const [id, agentData] of Object.entries(this.state.agents)) {
      const g = createSprite(agentData);
      this.layerAgents.appendChild(g);
      this._sprites[id] = g;

      // Click handler for agent selection
      g.style.cursor = 'pointer';
      g.addEventListener('click', () => {
        this.state.selectAgent(id);
      });
    }
  }

  _updateAgents() {
    for (const [id, agentData] of Object.entries(this.state.agents)) {
      const g = this._sprites[id];
      if (g) {
        updateSprite(g, agentData);
      }
    }
  }

  _updateActiveTurn() {
    // Clear all active
    for (const g of Object.values(this._sprites)) {
      g.dataset.activeTurn = 'false';
    }
    // Set current
    if (this.state.activeAgent && this._sprites[this.state.activeAgent]) {
      this._sprites[this.state.activeAgent].dataset.activeTurn = 'true';
    }
  }

  _updateHeader() {
    const phaseBadge = document.getElementById('phase-badge');
    const roundBadge = document.getElementById('round-badge');

    const phaseLabels = {
      idle: 'IDLE',
      setup: 'SETUP',
      generating_lore: 'GENERATING LORE',
      pre_battle: 'PRE-BATTLE',
      combat: 'COMBAT',
      victory: 'VICTORY',
    };
    phaseBadge.textContent = phaseLabels[this.state.phase] || this.state.phase.toUpperCase();

    if (this.state.phase === 'combat') {
      roundBadge.textContent = `Round ${this.state.round}`;
      roundBadge.classList.remove('badge-dim');
    } else {
      roundBadge.textContent = 'Round \u2014';
      roundBadge.classList.add('badge-dim');
    }
  }

  _playActionAnimation(event) {
    if (!event) return;

    const agentG = this._sprites[event.agent_id];
    if (!agentG) return;

    const details = event.details || {};

    if (event.action_type === 'attack' || event.action_type === 'ability') {
      const targetId = event.target_agent || details.target;
      const targetG = targetId ? this._sprites[targetId] : null;
      const targetData = targetId ? this.state.agents[targetId] : null;
      const agentData = this.state.agents[event.agent_id];

      if (targetG && agentData && targetData) {
        // Lunge animation
        const lungeClass = getLungeDirection(agentData.x, agentData.y, targetData.x, targetData.y);
        agentG.classList.add(lungeClass);
        setTimeout(() => agentG.classList.remove(lungeClass), 400);

        // Damage flash on target
        if (details.hit !== false && details.damage > 0) {
          targetG.classList.add('anim-damage-flash');
          setTimeout(() => targetG.classList.remove('anim-damage-flash'), 300);
        }

        // Floating damage number
        const targetCx = targetData.x * CELL_SIZE + CELL_SIZE / 2;
        const targetCy = targetData.y * CELL_SIZE + CELL_SIZE / 4;

        if (details.hit === false) {
          spawnDamageNumber(this.layerEffects, targetCx, targetCy, 'MISS', 'miss');
        } else if (details.damage > 0) {
          const isCrit = details.crit;
          const cls = isCrit ? 'crit' : 'dmg';
          const text = isCrit ? `${details.damage}!` : String(details.damage);
          spawnDamageNumber(this.layerEffects, targetCx, targetCy, text, cls);

          // Crit shake
          if (isCrit) {
            const gridPanel = document.getElementById('panel-grid');
            gridPanel.classList.add('anim-crit-shake');
            setTimeout(() => gridPanel.classList.remove('anim-crit-shake'), 300);
          }
        }

        // Counter damage
        if (details.counter && details.counter_damage > 0) {
          const agentCx = agentData.x * CELL_SIZE + CELL_SIZE / 2;
          const agentCy = agentData.y * CELL_SIZE + CELL_SIZE / 4;
          setTimeout(() => {
            spawnDamageNumber(this.layerEffects, agentCx, agentCy,
              String(details.counter_damage), 'counter');
          }, 300);
        }
      }
    } else if (event.action_type === 'defend') {
      agentG.classList.add('anim-defend');
      setTimeout(() => agentG.classList.remove('anim-defend'), 600);
    }

    // Heal effects from abilities
    if (event.action_type === 'ability' && event.description) {
      const healMatch = event.description.match(/heals for (\d+) HP/);
      if (healMatch) {
        const agentData = this.state.agents[event.agent_id];
        if (agentData) {
          const cx = agentData.x * CELL_SIZE + CELL_SIZE / 2;
          const cy = agentData.y * CELL_SIZE + CELL_SIZE / 4;
          spawnDamageNumber(this.layerEffects, cx, cy, `+${healMatch[1]}`, 'heal');
        }
      }
    }
  }

  _playDeathAnimation(data) {
    if (!data) return;
    const g = this._sprites[data.agent_id];
    if (g) {
      g.classList.add('anim-death');
    }
  }
}
