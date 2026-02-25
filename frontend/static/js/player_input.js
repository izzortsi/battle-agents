/**
 * player_input.js — Phase 2B: minimal DOM overlay to submit player actions.
 *
 * Responsibilities:
 * - Show/hide overlay when state.awaitingPlayer is set/cleared
 * - Let user choose mode: Move / Attack / Wait
 * - Highlight legal tiles/targets via isometric renderer (window._iso)
 * - Send {type:"player_action", ...} via window._sendWS (exposed by main.js)
 *
 * This is intentionally minimal and battle-agents styled (DOM overlay),
 * not tactics-arena UI.
 */

(function () {
  function qs(id) { return document.getElementById(id); }

  function esc(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function setHidden(el, hidden) {
    if (!el) return;
    if (hidden) el.classList.add('hidden');
    else el.classList.remove('hidden');
  }

  function inSet(val, setLike) {
    if (!setLike) return false;
    return setLike.has ? setLike.has(val) : false;
  }

  function buildMoveSet(legalActions) {
    const s = new Set();
    const moves = (legalActions && legalActions.valid_moves) || [];
    for (const t of moves) s.add(t);
    return s;
  }

  function buildAttackTargetSet(legalActions) {
    const s = new Set();
    const targets = (legalActions && legalActions.attack_targets) || [];
    for (const t of targets) {
      if (t && t.agent_id) s.add(t.agent_id);
    }
    return s;
  }

  function setHint(text) {
    const el = qs('player-action-hint');
    if (el) el.textContent = text || '';
  }

  function setTitle(text) {
    const el = qs('player-action-title');
    if (el) el.textContent = text || 'Your Turn';
  }

  function ensureGlobals() {
    const state = window._gameState;
    const send = window._sendWS;
    const iso = window._iso;

    if (!state) {
      console.warn('player_input.js: missing window._gameState');
      return null;
    }
    if (!send) {
      console.warn('player_input.js: missing window._sendWS');
      return null;
    }
    if (!iso) {
      console.warn('player_input.js: missing window._iso (isometric renderer)');
      return null;
    }
    return { state, send, iso };
  }

  function updateOverlay() {
    const g = ensureGlobals();
    if (!g) return;
    const { state } = g;

    const overlay = qs('player-action-overlay');
    const awaiting = state.awaitingPlayer;

    if (!awaiting) {
      setHidden(overlay, true);
      // Collapse ability list when turn ends
      const al = qs('ability-list');
      if (al) al.classList.add('hidden');
      return;
    }

    setHidden(overlay, false);

    const agent = state.agents && state.agents[awaiting.agentId];
    const name = agent ? agent.name : awaiting.agentId;
    setTitle(`${name}'s Turn`);

    const legal = awaiting.legalActions || {};
    const canMove = legal.valid_moves && legal.valid_moves.length > 0;
    const canAbility = (legal.abilities || []).some(a => a.can_use);

    const btnMove = qs('btn-act-move');
    const btnAttack = qs('btn-act-attack');
    const btnAbilities = qs('btn-act-abilities');
    const btnChat = qs('btn-act-chat');
    const chatRow = qs('player-chat-row');
    const chatInput = qs('player-chat-input');

    const btnDefend = qs('btn-act-defend');

    const canAttack = legal.attack_targets && legal.attack_targets.length > 0;
    const canChat = legal.chat_targets && legal.chat_targets.length > 0;

    if (btnMove) btnMove.disabled = !canMove;
    if (btnAttack) btnAttack.disabled = !canAttack;
    if (btnAbilities) btnAbilities.disabled = !canAbility;
    if (btnChat) btnChat.disabled = !canChat;
    if (btnDefend) btnDefend.disabled = !legal.can_defend;

    if (state.playerMode === 'move') {
      setHint('Move: click a highlighted tile. [Esc] to cancel.');
      if (chatRow) chatRow.classList.add('hidden');
    } else if (state.playerMode === 'attack') {
      setHint('Attack: click a highlighted enemy. [Esc] to cancel.');
      if (chatRow) chatRow.classList.add('hidden');
    } else if (state.playerMode === 'ability') {
      setHint(`${state.selectedAbilityName || 'Ability'}: click a highlighted target. [Esc] to cancel.`);
      if (chatRow) chatRow.classList.add('hidden');
    } else if (state.playerMode === 'chat') {
      setHint('Chat: type a message, then click a highlighted target. [Esc] to cancel.');
      if (chatRow) chatRow.classList.remove('hidden');
      if (chatInput) chatInput.focus();
    } else {
      setHint('Choose an action.');
      if (chatRow) chatRow.classList.add('hidden');
    }
  }

  function rerenderIso() {
    const g = ensureGlobals();
    if (!g) return;
    g.iso.setState(g.state);
    g.iso.renderFull();
  }

  function setMode(mode) {
    const g = ensureGlobals();
    if (!g) return;
    const { state } = g;

    state.playerMode = mode;
    // Clear hover preview when committing to a mode.
    state.hoverMode = null;
    state.hoverAbilityName = null;
    // Reuse existing renderer hook: awaiting_player triggers canvas repaint.
    state.notify('awaiting_player', { agent_id: state.awaitingPlayer?.agentId || '' });
    updateOverlay();
  }

  function sendPlayerAction(payload) {
    const g = ensureGlobals();
    if (!g) return;

    const awaiting = g.state.awaitingPlayer;
    const agentId = awaiting ? awaiting.agentId : null;

    g.send({ type: 'player_action', agent_id: agentId || undefined, ...payload });
    setHint('Submitted. Waiting for resolution...');
  }

  function renderAbilityList() {
    const g = ensureGlobals();
    if (!g) return;
    const { state } = g;

    const container = qs('ability-list');
    if (!container) return;

    const awaiting = state.awaitingPlayer;
    if (!awaiting) { container.classList.add('hidden'); return; }

    const legal = awaiting.legalActions || {};
    const abilities = legal.abilities || [];

    container.innerHTML = '';

    if (abilities.length === 0) {
      container.innerHTML = '<div style="font-size:11px;color:var(--text-dim);padding:4px 0">No abilities available.</div>';
      return;
    }

    for (const ab of abilities) {
      const card = document.createElement('div');
      const isSelected = state.selectedAbilityName === ab.name;
      card.className = 'action-ability-card'
        + (ab.can_use ? '' : ' action-ability-card-disabled')
        + (isSelected ? ' action-ability-card-selected' : '');

      const cdHtml = ab.cooldown_remaining > 0
        ? ` <span class="action-ab-cd">CD:${ab.cooldown_remaining}</span>` : '';
      const selfTag = ab.is_self_targeting
        ? ' <span style="font-size:10px;color:var(--accent-gold)">[self]</span>' : '';
      const lbTag = ab.is_limit_break
        ? ' <span class="action-ab-lb">LB</span>' : '';

      card.innerHTML =
        `<div class="action-ab-header">` +
          `<span class="action-ab-name">${esc(ab.name)}${selfTag}${lbTag}</span>` +
          `<span class="action-ab-cost">${ab.mana_cost}MP</span>` +
          cdHtml +
        `</div>` +
        `<div class="action-ab-meta">DMG:${ab.damage} | Rng:${ab.range} | ${esc(ab.aoe_pattern)}</div>` +
        (ab.description ? `<div class="action-ab-desc">${esc(ab.description)}</div>` : '');

      if (ab.can_use) {
        card.addEventListener('click', () => {
          if (ab.is_self_targeting) {
            // Self-targeting: no target selection needed — send immediately
            sendPlayerAction({ action_type: 'ability', ability_name: ab.name });
            container.classList.add('hidden');
          } else if (ab.targets && ab.targets.length === 0) {
            // No reachable targets right now — do nothing
            setHint(`${ab.name}: no targets in range.`);
          } else {
            // Enter ability-target mode
            const gInner = ensureGlobals();
            if (gInner) {
              gInner.state.selectedAbilityName = ab.name;
              setMode('ability');
            }
            container.classList.add('hidden');
          }
        });
        // Hover preview: show ability targets on canvas without committing to the mode
        card.addEventListener('mouseenter', () => {
          const gHov = ensureGlobals();
          if (!gHov || gHov.state.playerMode !== 'idle') return;
          gHov.state.hoverMode = 'ability';
          gHov.state.hoverAbilityName = ab.name;
          gHov.iso.setState(gHov.state); gHov.iso.renderFull();
        });
        card.addEventListener('mouseleave', () => {
          const gHov = ensureGlobals();
          if (!gHov || gHov.state.hoverAbilityName !== ab.name) return;
          gHov.state.hoverMode = null;
          gHov.state.hoverAbilityName = null;
          gHov.iso.setState(gHov.state); gHov.iso.renderFull();
        });
      }

      container.appendChild(card);
    }
  }

  function wireButtons() {
    const btnMove = qs('btn-act-move');
    const btnAttack = qs('btn-act-attack');
    const btnAbilities = qs('btn-act-abilities');
    const btnChat = qs('btn-act-chat');
    const btnDefend = qs('btn-act-defend');
    const btnWait = qs('btn-act-wait');

    if (btnMove) {
      btnMove.addEventListener('click', () => setMode('move'));
      btnMove.addEventListener('mouseenter', () => {
        const g = ensureGlobals();
        if (!g || !g.state.awaitingPlayer || g.state.playerMode !== 'idle') return;
        g.state.hoverMode = 'move';
        g.iso.setState(g.state); g.iso.renderFull();
      });
      btnMove.addEventListener('mouseleave', () => {
        const g = ensureGlobals();
        if (!g || g.state.hoverMode !== 'move') return;
        g.state.hoverMode = null;
        g.iso.setState(g.state); g.iso.renderFull();
      });
    }
    if (btnAttack) {
      btnAttack.addEventListener('click', () => setMode('attack'));
      btnAttack.addEventListener('mouseenter', () => {
        const g = ensureGlobals();
        if (!g || !g.state.awaitingPlayer || g.state.playerMode !== 'idle') return;
        g.state.hoverMode = 'attack';
        g.iso.setState(g.state); g.iso.renderFull();
      });
      btnAttack.addEventListener('mouseleave', () => {
        const g = ensureGlobals();
        if (!g || g.state.hoverMode !== 'attack') return;
        g.state.hoverMode = null;
        g.iso.setState(g.state); g.iso.renderFull();
      });
    }
    if (btnChat) {
      btnChat.addEventListener('click', () => setMode('chat'));
      btnChat.addEventListener('mouseenter', () => {
        const g = ensureGlobals();
        if (!g || !g.state.awaitingPlayer || g.state.playerMode !== 'idle') return;
        g.state.hoverMode = 'chat';
        g.iso.setState(g.state); g.iso.renderFull();
      });
      btnChat.addEventListener('mouseleave', () => {
        const g = ensureGlobals();
        if (!g || g.state.hoverMode !== 'chat') return;
        g.state.hoverMode = null;
        g.iso.setState(g.state); g.iso.renderFull();
      });
    }

    if (btnAbilities) btnAbilities.addEventListener('click', () => {
      const container = qs('ability-list');
      if (!container) return;
      if (container.classList.contains('hidden')) {
        renderAbilityList();
        container.classList.remove('hidden');
        // Show list without changing action mode
        const g = ensureGlobals();
        if (g && g.state.playerMode !== 'idle') setMode('idle');
      } else {
        container.classList.add('hidden');
      }
    });

    if (btnDefend) btnDefend.addEventListener('click', () => {
      const g = ensureGlobals();
      if (!g) return;
      const awaiting = g.state.awaitingPlayer;
      if (!awaiting) return;
      sendPlayerAction({ action_type: 'defend' });
    });

    if (btnWait) btnWait.addEventListener('click', () => {
      const g = ensureGlobals();
      if (!g) return;
      const awaiting = g.state.awaitingPlayer;
      if (!awaiting) return;
      sendPlayerAction({ action_type: 'wait' });
    });
  }

  function wireCanvasZoom() {
    const canvas = qs('battle-grid');
    if (!canvas) return;

    canvas.addEventListener('wheel', (evt) => {
      if (!evt.ctrlKey) return;
      const g = ensureGlobals();
      if (!g || !g.iso || typeof g.iso.adjustZoom !== 'function') return;
      evt.preventDefault();
      g.iso.adjustZoom(evt.deltaY);
    }, { passive: false });
  }

  function wireCanvasClicks() {
    const canvas = qs('battle-grid');
    if (!canvas) return;

    canvas.addEventListener('click', (evt) => {
      const g = ensureGlobals();
      if (!g) return;
      const { state, iso } = g;

      if (evt.ctrlKey && iso && typeof iso.rotateCW === 'function') {
        evt.preventDefault();
        iso.rotateCW();
        return;
      }

      const awaiting = state.awaitingPlayer;
      if (!awaiting) return;

      const legal = awaiting.legalActions || {};
      const rect = canvas.getBoundingClientRect();
      const px = evt.clientX - rect.left;
      const py = evt.clientY - rect.top;

      const pick = iso.pickAt(px, py);
      if (!pick) return;

      if (state.playerMode === 'move' && pick.kind === 'tile') {
        const validMoves = buildMoveSet(legal);
        if (!validMoves.has(pick.tile)) return;
        sendPlayerAction({ action_type: 'move', target_tile: pick.tile });
        return;
      }

      if (state.playerMode === 'attack' && pick.kind === 'unit') {
        const targets = buildAttackTargetSet(legal);
        if (!targets.has(pick.agentId)) return;
        sendPlayerAction({ action_type: 'attack', target_agent: pick.agentId });
        return;
      }

      if (state.playerMode === 'chat' && pick.kind === 'unit') {
        const targets = new Set((legal.chat_targets || []).map(t => t.agent_id));
        if (!targets.has(pick.agentId)) return;
        const input = qs('player-chat-input');
        const message = input ? input.value : '';
        sendPlayerAction({ action_type: 'chat', target_agent: pick.agentId, message });
        if (input) input.value = '';
        setMode('idle');
        return;
      }

      if (state.playerMode === 'ability' && state.selectedAbilityName && pick.kind === 'unit') {
        const abilityName = state.selectedAbilityName;
        const legalAbs = legal.abilities || [];
        const ab = legalAbs.find(a => a.name === abilityName);
        if (!ab || !ab.can_use) return;
        const targetIds = new Set((ab.targets || []).map(t => t.agent_id));
        if (!targetIds.has(pick.agentId)) return;
        sendPlayerAction({ action_type: 'ability', ability_name: abilityName, target_agent: pick.agentId });
        return;
      }
    });
  }

  function wireEscCancel() {
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      const g = ensureGlobals();
      if (!g) return;
      const { state } = g;
      if (!state.awaitingPlayer) return;
      if (state.playerMode !== 'idle') {
        state.selectedAbilityName = null;
        setMode('idle');
        const al = qs('ability-list');
        if (al) al.classList.add('hidden');
      }
    });
  }

  function wireChatInput() {
    const input = qs('player-chat-input');
    if (!input) return;

    input.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter') return;

      const g = ensureGlobals();
      if (!g) return;
      const { state } = g;

      if (!state.awaitingPlayer || state.playerMode !== 'chat') return;

      const legal = state.awaitingPlayer.legalActions || {};
      const targets = (legal.chat_targets || []).map(t => t.agent_id).filter(Boolean);
      const message = input.value || '';

      if (targets.length === 1) {
        sendPlayerAction({ action_type: 'chat', target_agent: targets[0], message });
        input.value = '';
        setMode('idle');
      } else {
        setHint('Select a target to send your message.');
      }
    });
  }

  function init() {
    wireButtons();
    wireCanvasZoom();
    wireCanvasClicks();
    wireEscCancel();
    wireChatInput();

    const g = ensureGlobals();
    if (!g) return;

    // Re-render overlay when state changes
    g.state.onChange((changeType) => {
      if (changeType === 'awaiting_player' || changeType === 'action' || changeType === 'snapshot') {
        updateOverlay();
      }
    });

    updateOverlay();
    rerenderIso();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
