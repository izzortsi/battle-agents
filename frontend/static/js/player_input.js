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
      return;
    }

    setHidden(overlay, false);

    const agent = state.agents && state.agents[awaiting.agentId];
    const name = agent ? agent.name : awaiting.agentId;
    setTitle(`${name}'s Turn`);

    const legal = awaiting.legalActions || {};
    const canMove = legal.valid_moves && legal.valid_moves.length > 0;
    const canAttack = legal.attack_targets && legal.attack_targets.length > 0;

    const btnMove = qs('btn-act-move');
    const btnAttack = qs('btn-act-attack');

    if (btnMove) btnMove.disabled = !canMove;
    if (btnAttack) btnAttack.disabled = !canAttack;

    if (state.playerMode === 'move') {
      setHint('Move: click a highlighted tile.');
    } else if (state.playerMode === 'attack') {
      setHint('Attack: click a highlighted enemy.');
    } else {
      setHint('Choose an action.');
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
    // Reuse existing renderer hook: awaiting_player triggers canvas repaint.
    state.notify('awaiting_player', { agent_id: state.awaitingPlayer?.agentId || '' });
    updateOverlay();
  }

  function sendPlayerAction(payload) {
    const g = ensureGlobals();
    if (!g) return;
    g.send({ type: 'player_action', ...payload });
    setHint('Submitted. Waiting for resolution...');
  }

  function wireButtons() {
    const btnMove = qs('btn-act-move');
    const btnAttack = qs('btn-act-attack');
    const btnWait = qs('btn-act-wait');

    if (btnMove) btnMove.addEventListener('click', () => setMode('move'));
    if (btnAttack) btnAttack.addEventListener('click', () => setMode('attack'));
    if (btnWait) btnWait.addEventListener('click', () => {
      const g = ensureGlobals();
      if (!g) return;
      const awaiting = g.state.awaitingPlayer;
      if (!awaiting) return;
      sendPlayerAction({ action_type: 'wait' });
    });
  }

  function wireCanvasClicks() {
    const canvas = qs('battle-grid');
    if (!canvas) return;

    canvas.addEventListener('click', (evt) => {
      const g = ensureGlobals();
      if (!g) return;
      const { state, iso } = g;

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
    });
  }

  function init() {
    wireButtons();
    wireCanvasClicks();

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
