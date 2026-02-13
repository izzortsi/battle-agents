/**
 * main.js — Entry point. Landing page, WebSocket connection and event routing.
 */

(function () {
  const state = new GameState();
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
      case 'turn_start':
        state.applyTurnStart(msg);
        break;
      case 'action':
        state.applyAction(msg);
        break;
      case 'dialogue':
        state.applyDialogue(msg);
        break;
      case 'cognitive':
        state.applyCognitive(msg);
        break;
      case 'death':
        state.applyDeath(msg);
        break;
      case 'victory':
        state.applyVictory(msg);
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
