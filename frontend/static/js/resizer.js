/* resizer.js — Draggable pane resize handles */

(function () {
  /* ── Main grid handles (bottom row only — right column removed) ── */

  const GRID_KEY = 'ba_panel_sizes';
  const GRID_DEFAULTS = { rowBottom: 200 };
  const GRID_LIMITS = {
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

  /* ── Init ── */

  function init() {
    gridSizes = loadGrid();
    applyGrid();
    setupGridHandle('resize-bottom', 'y', 'rowBottom', true);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
