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
    this._modelOverrides = this._loadModelOverrides(); // user-selected overrides (persisted)
    this._spritePresets = [];  // available sprite presets from /api/sprites
    this._spriteAssignments = this._loadSpriteAssignments(); // char_id -> preset_id

    // Campaign state
    this._campaigns = [];
    this._activeCampaignId = null;  // null = standalone mode

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
            <label>Sprite</label>
            <select id="create-sprite">
              <option value="">Auto (from class)</option>
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
      <div class="campaign-section" id="campaign-section">
        <h3>Campaign Mode</h3>
        <div class="campaign-controls">
          <input type="text" id="campaign-name" placeholder="New campaign name...">
          <button class="btn-campaign-create" id="btn-campaign-create">Create</button>
          <button class="btn-campaign-exit" id="btn-campaign-exit" style="display:none">Exit Campaign</button>
        </div>
        <div class="campaign-list" id="campaign-list"></div>
        <div class="campaign-roster" id="campaign-roster" style="display:none"></div>
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
    document.getElementById('btn-campaign-create').addEventListener('click', () => this._createCampaign());
    document.getElementById('btn-campaign-exit').addEventListener('click', () => this._exitCampaign());
  }

  async _fetchData() {
    try {
      const [charsRes, modelsRes, spritesRes, campaignsRes] = await Promise.all([
        fetch('/api/characters'),
        fetch('/api/models'),
        fetch('/api/sprites'),
        fetch('/api/campaigns'),
      ]);
      this._characters = await charsRes.json();
      this._models = await modelsRes.json();
      this._spritePresets = await spritesRes.json();
      this._campaigns = await campaignsRes.json();

      // No characters selected by default — user picks manually

      // YAML sprites always win — override any stale localStorage value
      for (const c of this._characters) {
        if (c.sprite) {
          this._spriteAssignments[c.id] = c.sprite;
        }
      }

      // Prune assignments that point to deleted spritesheets
      const validIds = new Set(this._spritePresets.map(p => p.id));
      for (const [id, preset] of Object.entries(this._spriteAssignments)) {
        if (preset && !validIds.has(preset)) {
          delete this._spriteAssignments[id];
        }
      }
      this._saveSpriteAssignments();

      // Populate the sprite dropdown in the create form
      const spriteSelect = document.getElementById('create-sprite');
      for (const preset of this._spritePresets) {
        const opt = document.createElement('option');
        opt.value = preset.id;
        opt.textContent = preset.label;
        spriteSelect.appendChild(opt);
      }

      this._renderRoster();
      this._renderModels();
      this._renderCampaigns();
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

      // Sprite preview (small thumbnail if assigned)
      const assignedSprite = this._spriteAssignments[c.id] || '';
      const previewHtml = assignedSprite
        ? `<div class="char-sprite-preview" style="background-image:url(/static/assets/spritesheets/${this._esc(assignedSprite)}.png?v=${ASSET_VERSION})"></div>`
        : '';

      const alignLabel = (c.moral_alignment || 'true_neutral').replace(/_/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase());
      const alignCss = this._alignmentCssClass(c.moral_alignment || 'true_neutral');

      div.innerHTML = `
        <input type="checkbox" ${this._selectedIds.has(c.id) ? 'checked' : ''}>
        ${previewHtml}
        <div class="char-roster-info">
          <div class="char-roster-name">${this._esc(c.name)}</div>
          <div class="char-roster-class">${this._esc(c.combat_class)}</div>
          <span class="alignment-badge ${alignCss}">${this._esc(alignLabel)}</span>
          <div class="char-roster-backstory">${this._esc(c.backstory)}</div>
        </div>
        <button class="char-delete-btn" title="Delete character">&times;</button>
      `;

      div.querySelector('.char-delete-btn').addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete "${c.name}"? This cannot be undone.`)) return;
        try {
          const res = await fetch(`/api/characters/${encodeURIComponent(c.id)}`, { method: 'DELETE' });
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          this._selectedIds.delete(c.id);
          this._characters = this._characters.filter(x => x.id !== c.id);
          this._generated = this._generated.filter(x => x.id !== c.id);
          delete this._spriteAssignments[c.id];
          this._saveSpriteAssignments();
          this._renderRoster();
        } catch (err) {
          console.error('Failed to delete character:', err);
          alert('Failed to delete character.');
        }
      });

      // Sprite selector dropdown (only if presets available)
      // Characters with a sprite from YAML/generation get a locked display.
      const hasBuiltInSprite = !!c.sprite;
      if (this._spritePresets.length > 0) {
        if (hasBuiltInSprite) {
          // Locked — show the assigned sprite name as a read-only label
          const lockedLabel = document.createElement('span');
          lockedLabel.className = 'char-sprite-locked';
          const preset = this._spritePresets.find(p => p.id === c.sprite);
          lockedLabel.textContent = preset ? preset.label : c.sprite.replace(/_/g, ' ');
          lockedLabel.title = 'Sprite assigned during creation';
          div.appendChild(lockedLabel);
        } else {
          const spriteSelect = document.createElement('select');
          spriteSelect.className = 'char-sprite-select';
          spriteSelect.title = 'Sprite preset';

          const noneOpt = document.createElement('option');
          noneOpt.value = '';
          noneOpt.textContent = 'No sprite';
          spriteSelect.appendChild(noneOpt);

          for (const preset of this._spritePresets) {
            const opt = document.createElement('option');
            opt.value = preset.id;
            opt.textContent = preset.label;
            if (assignedSprite === preset.id) opt.selected = true;
            spriteSelect.appendChild(opt);
          }

          spriteSelect.addEventListener('click', (e) => e.stopPropagation());
          spriteSelect.addEventListener('change', () => {
            if (spriteSelect.value) {
              this._spriteAssignments[c.id] = spriteSelect.value;
            } else {
              delete this._spriteAssignments[c.id];
            }
            this._saveSpriteAssignments();
            this._renderRoster(); // re-render to update preview
          });

          div.appendChild(spriteSelect);
        }
      }

      const checkbox = div.querySelector('input[type="checkbox"]');
      div.addEventListener('click', (e) => {
        if (e.target.tagName === 'SELECT' || e.target.tagName === 'OPTION' || e.target.tagName === 'BUTTON') return;
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
      // Prefer persisted override, then config routing, then default
      const savedVal = this._modelOverrides[role];
      const currentVal = savedVal || routing[role] || this._models.default || '';

      for (const adapter of adapters) {
        const opt = document.createElement('option');
        opt.value = adapter;
        opt.textContent = adapter;
        if (adapter === currentVal) opt.selected = true;
        select.appendChild(opt);
      }

      // Track the effective value (even if user hasn't changed it yet)
      if (savedVal) {
        this._modelOverrides[role] = savedVal;
      }

      select.addEventListener('change', () => {
        this._modelOverrides[role] = select.value;
        this._saveModelOverrides();
      });

      row.appendChild(label);
      row.appendChild(select);
      grid.appendChild(row);
    }
  }

  async _generateCharacter() {
    const name = document.getElementById('create-name').value.trim();
    const desc = document.getElementById('create-desc').value.trim();
    const sprite = document.getElementById('create-sprite').value;
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
        body: JSON.stringify({ name, description: desc, sprite, save }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const data = await res.json();
      this._generated.push(data);
      this._selectedIds.add(data.id);

      // Auto-assign the generated sprite
      if (data.sprite) {
        this._spriteAssignments[data.id] = data.sprite;
      }

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

  // ===== Campaign methods =====

  _renderCampaigns() {
    const list = document.getElementById('campaign-list');
    list.innerHTML = '';

    if (this._campaigns.length === 0) {
      list.innerHTML = '<div class="campaign-empty">No campaigns yet. Create one above.</div>';
      return;
    }

    for (const c of this._campaigns) {
      const item = document.createElement('div');
      item.className = 'campaign-item' + (this._activeCampaignId === c.id ? ' active' : '');
      item.innerHTML = `
        <div class="campaign-item-info">
          <span class="campaign-item-name">${this._esc(c.name)}</span>
          <span class="campaign-item-meta">Battles: ${c.battle_count}</span>
        </div>
        <button class="campaign-item-delete" title="Delete campaign">&times;</button>
      `;

      item.querySelector('.campaign-item-info').addEventListener('click', () => {
        this._selectCampaign(c.id);
      });

      item.querySelector('.campaign-item-delete').addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!confirm(`Delete campaign "${c.name}"? This cannot be undone.`)) return;
        try {
          await fetch(`/api/campaigns/${c.id}`, { method: 'DELETE' });
          if (this._activeCampaignId === c.id) this._exitCampaign();
          this._campaigns = this._campaigns.filter(x => x.id !== c.id);
          this._renderCampaigns();
        } catch (err) {
          console.error('Failed to delete campaign:', err);
        }
      });

      list.appendChild(item);
    }
  }

  async _selectCampaign(campaignId) {
    this._activeCampaignId = campaignId;

    // Fetch full campaign data
    try {
      const res = await fetch(`/api/campaigns/${campaignId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      this._activeCampaignData = await res.json();
    } catch (err) {
      console.error('Failed to fetch campaign:', err);
      this._activeCampaignId = null;
      return;
    }

    // Update UI state
    document.getElementById('landing-chars').style.display = 'none';
    document.getElementById('btn-campaign-exit').style.display = '';
    this._renderCampaigns();
    this._renderCampaignRoster();
    this._updateBeginButton();
  }

  _exitCampaign() {
    this._activeCampaignId = null;
    this._activeCampaignData = null;
    document.getElementById('landing-chars').style.display = '';
    document.getElementById('btn-campaign-exit').style.display = 'none';
    document.getElementById('campaign-roster').style.display = 'none';
    this._renderCampaigns();
    this._updateBeginButton();
  }

  _renderCampaignRoster() {
    const container = document.getElementById('campaign-roster');
    if (!this._activeCampaignData) {
      container.style.display = 'none';
      return;
    }

    container.style.display = '';
    container.innerHTML = '';

    const data = this._activeCampaignData;

    // Campaign header
    const header = document.createElement('div');
    header.className = 'campaign-roster-header';
    const alive = data.roster.filter(r => r.alive).length;
    header.innerHTML = `
      <div class="campaign-roster-title">${this._esc(data.name)}</div>
      <div class="campaign-roster-meta">
        Battle #${data.battle_count + 1} | Roster: ${alive}/${data.roster.length} alive
      </div>
    `;
    container.appendChild(header);

    // Roster entries
    for (const r of data.roster) {
      const entry = document.createElement('div');
      entry.className = 'campaign-roster-entry' + (r.alive ? '' : ' dead');

      // Sprite preview
      const spriteHtml = r.sprite
        ? `<div class="char-sprite-preview" style="background-image:url(/static/assets/spritesheets/${this._esc(r.sprite)}.png?v=${ASSET_VERSION})"></div>`
        : '';

      // XP bar
      const xpPct = r.xp_to_next > 0 ? Math.min(100, (r.xp / r.xp_to_next) * 100) : 100;

      const campAlignLabel = r.alignment_label || 'True Neutral';
      const campAlignCss = this._alignmentCssClass(
        (r.alignment_label || 'True Neutral').toLowerCase().replace(/ /g, '_')
      );
      const campMorality = (r.morality != null ? r.morality : 0).toFixed(2);
      const campOrder = (r.order_value != null ? r.order_value : 0).toFixed(2);

      entry.innerHTML = `
        ${spriteHtml}
        <div class="campaign-roster-info">
          <div class="campaign-roster-name">
            ${this._esc(r.name)}
            <span class="campaign-roster-level">Lv.${r.level}</span>
            ${!r.alive ? '<span class="campaign-roster-dead-tag">FALLEN</span>' : ''}
          </div>
          <div class="campaign-roster-class">${this._esc(r.combat_class)}</div>
          <div class="campaign-roster-alignment">
            <span class="alignment-badge ${campAlignCss}">${this._esc(campAlignLabel)}</span>
            <span class="alignment-values">G/E:${campMorality} L/C:${campOrder}</span>
          </div>
          <div class="campaign-roster-xp">
            <div class="xp-bar"><div class="xp-bar-fill" style="width:${xpPct}%"></div></div>
            <span class="xp-label">${r.xp}/${r.xp_to_next} XP</span>
          </div>
          <div class="campaign-roster-stats">
            ATK:${r.atk} MGK:${r.mgk} SPD:${r.spd} CON:${r.con} HIT:${r.hit}
          </div>
        </div>
      `;

      container.appendChild(entry);
    }

    // Battle history summary
    if (data.battles && data.battles.length > 0) {
      const historySection = document.createElement('div');
      historySection.className = 'campaign-history';
      historySection.innerHTML = '<div class="campaign-history-title">Battle History</div>';

      for (const b of data.battles.slice(-5).reverse()) {
        const bDiv = document.createElement('div');
        bDiv.className = 'campaign-history-entry';
        const winners = b.winner_ids || [];
        const deaths = b.death_ids || [];
        bDiv.innerHTML = `
          <span class="campaign-history-num">#${b.battle_num}</span>
          <span class="campaign-history-detail">
            ${b.rounds} rounds | ${winners.length} winner${winners.length !== 1 ? 's' : ''} | ${deaths.length} death${deaths.length !== 1 ? 's' : ''}
          </span>
        `;
        historySection.appendChild(bDiv);
      }

      container.appendChild(historySection);
    }
  }

  _updateBeginButton() {
    const btn = document.getElementById('btn-begin');
    if (this._activeCampaignId && this._activeCampaignData) {
      const alive = this._activeCampaignData.roster.filter(r => r.alive).length;
      if (alive < 2) {
        btn.textContent = 'Campaign Over (< 2 alive)';
        btn.disabled = true;
      } else {
        btn.textContent = `Begin Campaign Battle #${this._activeCampaignData.battle_count + 1}`;
        btn.disabled = false;
      }
    } else {
      btn.textContent = 'Begin Battle';
      btn.disabled = false;
    }
  }

  async _createCampaign() {
    const nameInput = document.getElementById('campaign-name');
    const name = nameInput.value.trim();
    if (!name) {
      alert('Enter a campaign name.');
      return;
    }

    const selectedChars = Array.from(this._selectedIds);
    if (selectedChars.length < 2) {
      alert('Select at least 2 characters for the campaign roster.');
      return;
    }

    const createBtn = document.getElementById('btn-campaign-create');
    createBtn.disabled = true;
    createBtn.textContent = 'Creating...';

    try {
      const res = await fetch('/api/campaigns', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, character_ids: selectedChars }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      nameInput.value = '';

      // Refresh campaigns list and select the new one
      const listRes = await fetch('/api/campaigns');
      this._campaigns = await listRes.json();
      await this._selectCampaign(data.id);
    } catch (err) {
      console.error('Failed to create campaign:', err);
      alert('Failed to create campaign.');
    } finally {
      createBtn.disabled = false;
      createBtn.textContent = 'Create';
    }
  }

  _beginBattle() {
    // Campaign mode
    if (this._activeCampaignId && this._activeCampaignData) {
      const alive = this._activeCampaignData.roster.filter(r => r.alive).length;
      if (alive < 2) {
        alert('Not enough alive characters to battle.');
        return;
      }

      const btn = document.getElementById('btn-begin');
      btn.disabled = true;
      btn.textContent = 'Starting...';

      const lorePrompt = document.getElementById('lore-prompt').value.trim();

      const config = {
        type: 'configure',
        campaign_id: this._activeCampaignId,
        lore_prompt: lorePrompt,
        models: Object.keys(this._modelOverrides).length > 0 ? this._modelOverrides : null,
      };

      this._onBeginBattle(config);
      return;
    }

    // Standalone mode
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

    // Build sprite assignments for selected characters only
    const sprites = {};
    for (const id of selectedChars) {
      if (this._spriteAssignments[id]) {
        sprites[id] = this._spriteAssignments[id];
      }
    }

    const config = {
      type: 'configure',
      characters: selectedChars,
      lore_prompt: lorePrompt,
      models: Object.keys(this._modelOverrides).length > 0 ? this._modelOverrides : null,
      sprites: Object.keys(sprites).length > 0 ? sprites : null,
    };

    this._onBeginBattle(config);
  }

  hide() {
    this.el.classList.add('hidden');
  }

  show() {
    this.el.classList.remove('hidden');
  }

  _loadModelOverrides() {
    try {
      const raw = localStorage.getItem('ba_model_routing');
      return raw ? JSON.parse(raw) : {};
    } catch { return {}; }
  }

  _saveModelOverrides() {
    try {
      localStorage.setItem('ba_model_routing', JSON.stringify(this._modelOverrides));
    } catch { /* quota exceeded or private mode — ignore */ }
  }

  _loadSpriteAssignments() {
    try {
      const raw = localStorage.getItem('ba_sprite_assignments');
      return raw ? JSON.parse(raw) : {};
    } catch { return {}; }
  }

  _saveSpriteAssignments() {
    try {
      localStorage.setItem('ba_sprite_assignments', JSON.stringify(this._spriteAssignments));
    } catch { /* quota exceeded or private mode */ }
  }

  _alignmentCssClass(key) {
    if (!key) return 'align-neutral';
    const k = key.toLowerCase().replace(/ /g, '_');
    if (k.includes('good')) return 'align-good';
    if (k.includes('evil')) return 'align-evil';
    if (k.includes('lawful')) return 'align-lawful';
    if (k.includes('chaotic')) return 'align-chaotic';
    return 'align-neutral';
  }

  _esc(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
}
