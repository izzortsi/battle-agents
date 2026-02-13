/**
 * landing.js — Landing page: character selection, creation, lore prompt, model routing.
 */

class LandingPage {
  constructor(onBeginBattle) {
    this._onBeginBattle = onBeginBattle;
    this._characters = [];     // from /api/characters
    this._generated = [];      // newly generated characters
    this._selectedIds = new Set();
    this._models = {};         // available adapters + routing
    this._modelOverrides = {}; // user-selected overrides

    this.el = document.getElementById('landing-page');
    this._initDOM();
    this._fetchData();
  }

  _initDOM() {
    this.el.innerHTML = `
      <div class="landing-title">Configure Battle</div>
      <div class="landing-grid">
        <div class="landing-section" id="landing-chars">
          <h3>Select Characters</h3>
          <div class="char-roster" id="char-roster"></div>
        </div>
        <div class="landing-section" id="landing-create">
          <h3>Create New Character</h3>
          <div class="create-form">
            <label>Name</label>
            <input type="text" id="create-name" placeholder="Character name...">
            <label>Description</label>
            <textarea id="create-desc" placeholder="Fighting style, personality, backstory..."></textarea>
            <label>Combat Class</label>
            <select id="create-class">
              <option value="warrior">Warrior</option>
              <option value="mage">Mage</option>
              <option value="rogue">Rogue</option>
              <option value="healer">Healer</option>
              <option value="ranger">Ranger</option>
            </select>
            <div class="form-row">
              <input type="checkbox" id="create-save" checked>
              <label for="create-save">Save to roster</label>
            </div>
            <button class="btn-generate" id="btn-generate">Generate Character</button>
            <div class="generate-status" id="generate-status"></div>
          </div>
        </div>
      </div>
      <div class="lore-section">
        <h3>World Lore (optional)</h3>
        <textarea id="lore-prompt" placeholder="Describe the world or setting for this battle..."></textarea>
      </div>
      <div class="model-section" id="model-section">
        <h3>Model Routing</h3>
        <div class="model-grid" id="model-grid"></div>
      </div>
      <div class="landing-actions">
        <button class="btn-begin" id="btn-begin">Begin Battle</button>
      </div>
    `;

    document.getElementById('btn-generate').addEventListener('click', () => this._generateCharacter());
    document.getElementById('btn-begin').addEventListener('click', () => this._beginBattle());
  }

  async _fetchData() {
    try {
      const [charsRes, modelsRes] = await Promise.all([
        fetch('/api/characters'),
        fetch('/api/models'),
      ]);
      this._characters = await charsRes.json();
      this._models = await modelsRes.json();

      // Select all characters by default
      for (const c of this._characters) {
        this._selectedIds.add(c.id);
      }

      this._renderRoster();
      this._renderModels();
    } catch (e) {
      console.error('Failed to fetch landing data:', e);
      document.getElementById('char-roster').innerHTML =
        '<div style="color:var(--accent);padding:8px">Failed to load characters. Is the server running?</div>';
    }
  }

  _renderRoster() {
    const roster = document.getElementById('char-roster');
    roster.innerHTML = '';

    const allChars = [...this._characters, ...this._generated];

    for (const c of allChars) {
      const isGenerated = this._generated.includes(c);
      const div = document.createElement('div');
      div.className = 'char-roster-item' + (this._selectedIds.has(c.id) ? ' selected' : '') + (isGenerated ? ' generated' : '');

      div.innerHTML = `
        <input type="checkbox" ${this._selectedIds.has(c.id) ? 'checked' : ''}>
        <div class="char-roster-info">
          <div class="char-roster-name">${this._esc(c.name)}</div>
          <div class="char-roster-class">${this._esc(c.combat_class)}</div>
          <div class="char-roster-backstory">${this._esc(c.backstory)}</div>
        </div>
      `;

      const checkbox = div.querySelector('input[type="checkbox"]');
      div.addEventListener('click', (e) => {
        if (e.target !== checkbox) {
          checkbox.checked = !checkbox.checked;
        }
        if (checkbox.checked) {
          this._selectedIds.add(c.id);
          div.classList.add('selected');
        } else {
          this._selectedIds.delete(c.id);
          div.classList.remove('selected');
        }
      });

      roster.appendChild(div);
    }
  }

  _renderModels() {
    const grid = document.getElementById('model-grid');
    grid.innerHTML = '';

    const adapters = this._models.adapters || [];
    const routing = this._models.routing || {};
    const roles = ['action_decision', 'reflection', 'planning', 'dialogue', 'commentary', 'lore_generation', 'character_generation'];

    for (const role of roles) {
      if (role === 'importance_rating') continue;

      const row = document.createElement('div');
      row.className = 'model-row';

      const label = document.createElement('label');
      label.textContent = role.replace(/_/g, ' ');

      const select = document.createElement('select');
      const currentVal = routing[role] || this._models.default || '';

      for (const adapter of adapters) {
        const opt = document.createElement('option');
        opt.value = adapter;
        opt.textContent = adapter;
        if (adapter === currentVal) opt.selected = true;
        select.appendChild(opt);
      }

      select.addEventListener('change', () => {
        this._modelOverrides[role] = select.value;
      });

      row.appendChild(label);
      row.appendChild(select);
      grid.appendChild(row);
    }
  }

  async _generateCharacter() {
    const name = document.getElementById('create-name').value.trim();
    const desc = document.getElementById('create-desc').value.trim();
    const cls = document.getElementById('create-class').value;
    const save = document.getElementById('create-save').checked;
    const btn = document.getElementById('btn-generate');
    const status = document.getElementById('generate-status');

    if (!name || !desc) {
      status.textContent = 'Name and description are required.';
      return;
    }

    btn.disabled = true;
    status.textContent = 'Generating character...';

    try {
      const res = await fetch('/api/characters/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description: desc, combat_class: cls, save }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const data = await res.json();
      this._generated.push(data);
      this._selectedIds.add(data.id);
      this._renderRoster();

      status.textContent = `Generated ${data.name}!`;
      document.getElementById('create-name').value = '';
      document.getElementById('create-desc').value = '';
    } catch (e) {
      status.textContent = `Error: ${e.message}`;
      console.error('Character generation failed:', e);
    } finally {
      btn.disabled = false;
    }
  }

  _beginBattle() {
    const selectedChars = Array.from(this._selectedIds);
    if (selectedChars.length < 2) {
      alert('Select at least 2 characters.');
      return;
    }

    // Disable button to prevent double-starts
    const btn = document.getElementById('btn-begin');
    btn.disabled = true;
    btn.textContent = 'Starting...';

    const lorePrompt = document.getElementById('lore-prompt').value.trim();

    const config = {
      type: 'configure',
      characters: selectedChars,
      lore_prompt: lorePrompt,
      models: Object.keys(this._modelOverrides).length > 0 ? this._modelOverrides : null,
    };

    this._onBeginBattle(config);
  }

  hide() {
    this.el.classList.add('hidden');
  }

  show() {
    this.el.classList.remove('hidden');
  }

  _esc(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
}
