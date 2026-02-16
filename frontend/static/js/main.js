/**
 * main.js — Entry point. Landing page, WebSocket connection, event routing, victory overlay.
 */

(function () {
  const state = new GameState();
  window._gameState = state;  // exposed for popup close handler in panels.js
  const renderer = new Renderer(state);

  // Wire up state changes to rendering
  state.onChange((changeType, detail) => {
    renderer.onStateChange(changeType, detail);
  });

  // WebSocket connection
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  let ws;
  let reconnectTimer = null;

  function connect() {
    ws = new WebSocket(`${protocol}//${location.host}/ws`);

    ws.onopen = () => {
      console.log('WebSocket connected');
    };

    ws.onmessage = (evt) => {
      let msg;
      try {
        msg = JSON.parse(evt.data);
      } catch (e) {
        console.error('Bad JSON from server:', e);
        return;
      }
      routeMessage(msg);
    };

    ws.onclose = () => {
      console.log('WebSocket disconnected, reconnecting in 2s...');
      reconnectTimer = setTimeout(connect, 2000);
    };

    ws.onerror = (err) => {
      console.error('WebSocket error:', err);
    };
  }

  function send(msg) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    }
  }

  function routeMessage(msg) {
    switch (msg.type) {
      case 'snapshot':
        transitionToBattle();
        state.applySnapshot(msg);
        break;
      case 'restore':
        transitionToBattle();
        state.applyRestore(msg);
        break;
      case 'phase':
        state.applyPhase(msg);
        break;
      case 'social_tick':
        state.applySocialTick(msg);
        break;
      case 'turn_start':
        state.applyTurnStart(msg);
        break;
      case 'action':
        state.applyAction(msg);
        break;
      case 'dialogue':
        state.applyDialogue(msg);
        break;
      case 'dialogue_session':
        state.applyDialogueSession(msg);
        break;
      case 'cognitive':
        state.applyCognitive(msg);
        break;
      case 'death':
        state.applyDeath(msg);
        break;
      case 'victory':
        state.applyVictory(msg);
        showVictoryOverlay();
        break;
      case 'damage_stats':
        state.applyDamageStats(msg);
        updateVictoryOverlay();
        break;
      case 'campaign_update':
        state.applyCampaignUpdate(msg);
        updateVictoryOverlay();
        break;
      case 'social_update':
        state.applySocialUpdate(msg);
        break;
      case 'lore':
        state.applyLore(msg);
        break;
      case 'commentary':
        state.applyCommentary(msg);
        break;
      default:
        console.warn('Unknown message type:', msg.type);
    }
  }

  // ===== Landing page → Battle transition =====

  let battleStarted = false;

  function transitionToBattle() {
    if (battleStarted) return;
    battleStarted = true;

    // Hide landing, show battle UI
    if (landing) landing.hide();
    document.getElementById('main').classList.remove('hidden');

    // Enable control buttons
    btnStep.disabled = false;
    btnPlay.disabled = false;
    btnPause.disabled = false;
  }

  // ===== Victory Overlay =====

  function esc(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function showVictoryOverlay() {
    // Remove any existing overlay
    const existing = document.getElementById('victory-overlay');
    if (existing) existing.remove();

    const v = state.victoryData;
    if (!v) return;

    const overlay = document.createElement('div');
    overlay.id = 'victory-overlay';
    overlay.className = 'victory-overlay';

    const title = v.winner_name
      ? `${esc(v.winner_name)} ${v.alliance_victory ? 'Win' : 'Wins'}!`
      : 'Draw';

    overlay.innerHTML = `
      <div class="victory-panel">
        <div class="victory-title">${title}</div>
        <div class="victory-subtitle">${v.rounds} round${v.rounds !== 1 ? 's' : ''}</div>
        <div id="victory-dmg-section"></div>
        <div id="victory-campaign-section"></div>
        <div class="victory-actions">
          <button class="btn-victory-continue" id="btn-victory-continue">
            ${landing._activeCampaignId ? 'Continue Campaign' : 'Return to Lobby'}
          </button>
        </div>
      </div>
    `;

    document.body.appendChild(overlay);

    document.getElementById('btn-victory-continue').addEventListener('click', () => {
      returnToLanding();
    });

    // Immediately render any stats already available
    updateVictoryOverlay();
  }

  function updateVictoryOverlay() {
    // Update damage stats section
    const dmgSection = document.getElementById('victory-dmg-section');
    if (dmgSection && state.damageStats && state.damageStats.length > 0) {
      const maxDmg = Math.max(...state.damageStats.map(s => s.damage), 1);
      let html = '<div class="victory-dmg-header">Damage Dealt</div>';
      for (const s of state.damageStats) {
        const pct = (s.damage / maxDmg) * 100;
        html += `
          <div class="victory-dmg-row">
            <span class="victory-dmg-name">${esc(s.name)}</span>
            <div class="victory-dmg-bar-bg">
              <div class="victory-dmg-bar-fill" style="width:${pct}%"></div>
            </div>
            <span class="victory-dmg-value">${s.damage}</span>
          </div>
        `;
      }
      dmgSection.innerHTML = html;
    }

    // Update campaign section
    const campSection = document.getElementById('victory-campaign-section');
    if (campSection && state.campaignUpdate) {
      const cu = state.campaignUpdate;
      const levelUpSet = new Set((cu.level_ups || []).map(l => l.agent_id));
      const deathSet = new Set(cu.deaths || []);

      let html = `
        <div class="victory-campaign">
          <div class="victory-campaign-title">Campaign Battle #${cu.battle_num} Results</div>
      `;

      // XP awards
      if (cu.roster) {
        for (const r of cu.roster) {
          const xpGained = (cu.xp_awards || {})[r.agent_id] || 0;
          if (xpGained === 0 && !deathSet.has(r.agent_id)) continue;
          html += `
            <div class="victory-xp-row">
              <span class="victory-xp-name">${esc(r.name)}</span>
              ${xpGained > 0 ? `<span class="victory-xp-amount">+${xpGained} XP</span>` : ''}
              ${levelUpSet.has(r.agent_id) ? `<span class="victory-levelup">LEVEL UP! Lv.${(cu.level_ups.find(l => l.agent_id === r.agent_id) || {}).level || ''}</span>` : ''}
              ${deathSet.has(r.agent_id) ? '<span class="victory-death-tag">FALLEN</span>' : ''}
            </div>
          `;
        }
      }

      html += '</div>';
      campSection.innerHTML = html;
    }
  }

  async function returnToLanding() {
    // Remove victory overlay
    const overlay = document.getElementById('victory-overlay');
    if (overlay) overlay.remove();

    // Hide battle UI, show landing
    document.getElementById('main').classList.add('hidden');
    landing.show();
    battleStarted = false;

    // Close popups if open
    if (isPopupOpen()) closeAgentPopup(state);
    closeLorePopup();
    closeDialoguePopup();

    // Reset state for next battle
    state.phase = 'idle';
    state.victoryData = null;
    state.damageStats = null;
    state.campaignUpdate = null;
    state.lore = null;
    state.dialogueSessions = [];

    // Reset lore popup content + hide button
    const loreContent = document.getElementById('popup-lore');
    if (loreContent) { loreContent.innerHTML = ''; loreContent.dataset.rendered = ''; }
    const loreBtn = document.getElementById('btn-lore');
    if (loreBtn) loreBtn.classList.add('hidden');

    // Re-enable controls
    btnStep.disabled = true;
    btnPlay.disabled = true;
    btnPause.disabled = true;

    // If in campaign mode, refresh campaign data
    if (landing._activeCampaignId) {
      await landing._selectCampaign(landing._activeCampaignId);
    }
  }

  // ===== Landing page =====

  const landing = new LandingPage((config) => {
    // Send configure message (always has type: 'configure')
    send(config);

    // Start simulation
    send({ type: 'start' });

    // Show starting phase
    document.getElementById('phase-badge').textContent = 'STARTING';
  });

  // ===== Control buttons =====

  const btnStart = document.getElementById('btn-start');
  const btnStep = document.getElementById('btn-step');
  const btnPlay = document.getElementById('btn-play');
  const btnPause = document.getElementById('btn-pause');
  const speedSlider = document.getElementById('speed-slider');
  const speedValue = document.getElementById('speed-value');

  btnStep.addEventListener('click', () => {
    send({ type: 'step' });
  });

  btnPlay.addEventListener('click', () => {
    send({ type: 'play' });
    btnPlay.disabled = true;
    btnPause.disabled = false;
  });

  btnPause.addEventListener('click', () => {
    send({ type: 'pause' });
    btnPlay.disabled = false;
    btnPause.disabled = true;
  });

  speedSlider.addEventListener('input', () => {
    const ms = parseInt(speedSlider.value);
    speedValue.textContent = ms + 'ms';
    send({ type: 'speed', delay: ms });
  });

  // Initial connection
  connect();
})();
