/* resizer.js — Draggable pane resize handles */

(function () {
  /* ── Main grid handles (right column + bottom row) ── */

  const GRID_KEY = 'ba_panel_sizes';
  const GRID_DEFAULTS = { colRight: 720, rowBottom: 200 };
  const GRID_LIMITS = {
    colRight: { min: 280, max: 1200 },
    rowBottom: { min: 80, max: 600 },
  };

  let gridSizes;

  function loadGrid() {
    try {
      const s = JSON.parse(localStorage.getItem(GRID_KEY));
      return s && typeof s === 'object' ? { ...GRID_DEFAULTS, ...s } : { ...GRID_DEFAULTS };
    } catch { return { ...GRID_DEFAULTS }; }
  }

  function saveGrid() {
    localStorage.setItem(GRID_KEY, JSON.stringify(gridSizes));
  }

  function applyGrid() {
    const main = document.getElementById('main');
    if (!main) return;
    main.style.setProperty('--col-right', gridSizes.colRight + 'px');
    main.style.setProperty('--row-bottom', gridSizes.rowBottom + 'px');
  }

  function clamp(val, min, max) {
    return Math.max(min, Math.min(max, val));
  }

  function setupGridHandle(id, axis, prop, invert) {
    const el = document.getElementById(id);
    if (!el) return;

    el.addEventListener('mousedown', function (e) {
      e.preventDefault();
      let last = axis === 'x' ? e.clientX : e.clientY;

      el.classList.add('dragging');
      document.body.style.cursor = axis === 'x' ? 'col-resize' : 'row-resize';
      document.body.style.userSelect = 'none';

      function onMove(e) {
        const pos = axis === 'x' ? e.clientX : e.clientY;
        const delta = pos - last;
        last = pos;
        const sign = invert ? -1 : 1;
        gridSizes[prop] = clamp(
          gridSizes[prop] + delta * sign,
          GRID_LIMITS[prop].min,
          GRID_LIMITS[prop].max,
        );
        applyGrid();
      }

      function onUp() {
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        el.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        saveGrid();
      }

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  }

  /* ── Info-pane intra-panel handles ── */

  const INFO_KEY = 'ba_info_flex';
  const INFO_DEFAULTS = {
    'character-panel': 2,
    'social-panel': 0.5,
    'cognitive-panel': 1,
  };
  const INFO_MIN_FLEX = 0.15;

  let infoFlex;

  function loadInfo() {
    try {
      const s = JSON.parse(localStorage.getItem(INFO_KEY));
      return s && typeof s === 'object' ? { ...INFO_DEFAULTS, ...s } : { ...INFO_DEFAULTS };
    } catch { return { ...INFO_DEFAULTS }; }
  }

  function saveInfo() {
    localStorage.setItem(INFO_KEY, JSON.stringify(infoFlex));
  }

  function applyInfo() {
    for (const [id, val] of Object.entries(infoFlex)) {
      const el = document.getElementById(id);
      if (el) el.style.flex = String(val);
    }
  }

  function setupInfoHandles() {
    const container = document.getElementById('panel-info');
    if (!container) return;

    const handles = container.querySelectorAll('.info-resize');

    handles.forEach(function (handle) {
      handle.addEventListener('mousedown', function (e) {
        e.preventDefault();
        const aboveId = handle.dataset.above;
        const belowId = handle.dataset.below;
        if (!(aboveId in infoFlex) || !(belowId in infoFlex)) return;

        let lastY = e.clientY;
        const totalFlex = Object.values(infoFlex).reduce(function (a, b) { return a + b; }, 0);
        const containerH = container.clientHeight;

        handle.classList.add('dragging');
        document.body.style.cursor = 'row-resize';
        document.body.style.userSelect = 'none';

        function onMove(e) {
          const delta = e.clientY - lastY;
          lastY = e.clientY;
          const flexDelta = (delta / containerH) * totalFlex;
          infoFlex[aboveId] = Math.max(INFO_MIN_FLEX, infoFlex[aboveId] + flexDelta);
          infoFlex[belowId] = Math.max(INFO_MIN_FLEX, infoFlex[belowId] - flexDelta);
          applyInfo();
        }

        function onUp() {
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
          handle.classList.remove('dragging');
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
          saveInfo();
        }

        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
      });
    });
  }

  /* ── Init ── */

  function init() {
    gridSizes = loadGrid();
    applyGrid();
    setupGridHandle('resize-right', 'x', 'colRight', true);
    setupGridHandle('resize-bottom', 'y', 'rowBottom', true);

    infoFlex = loadInfo();
    applyInfo();
    setupInfoHandles();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
