/**
 * panels.js — UI panel rendering: agent cards, battle log, dialogue, social, cognitive.
 */

// ===== Agent Cards (left panel) =====

function renderCards(state) {
  const container = document.getElementById('agent-cards');
  if (!container) return;

  // Preserve scroll position
  const scrollTop = container.scrollTop;

  container.innerHTML = '';

  // Sort: alive first, then by turn order
  const ids = Object.keys(state.agents);
  ids.sort((a, b) => {
    const aa = state.agents[a];
    const bb = state.agents[b];
    if (aa.is_alive !== bb.is_alive) return aa.is_alive ? -1 : 1;
    const ai = state.turnOrder.indexOf(a);
    const bi = state.turnOrder.indexOf(b);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });

  for (const id of ids) {
    const agent = state.agents[id];
    const card = document.createElement('div');
    card.className = 'agent-card';
    if (!agent.is_alive) card.classList.add('dead');
    if (state.activeAgent === id) card.classList.add('active');
    if (state.selectedAgent === id) card.style.borderColor = '#4169e1';

    const hpPct = agent.max_hp > 0 ? agent.hp / agent.max_hp : 0;
    const hpClass = hpPct > 0.6 ? 'hp' : hpPct > 0.3 ? 'hp warn' : 'hp crit';
    const manaPct = agent.max_mana > 0 ? agent.mana / agent.max_mana : 0;

    // Last action
    const lastAction = state.eventLog.filter(e => e.agentId === id).slice(-1)[0];
    const actionText = lastAction ? truncate(lastAction.description, 40) : '';

    card.innerHTML = `
      <div class="card-name">${escHtml(agent.name)}</div>
      <div class="card-class">${escHtml(agent.combat_class)}</div>
      <div class="card-bars">
        <div class="bar-row">
          <span class="bar-label">HP</span>
          <div class="bar-bg"><div class="bar-fill ${hpClass}" style="width:${hpPct * 100}%"></div></div>
          <span class="bar-value">${agent.hp}/${agent.max_hp}</span>
        </div>
        <div class="bar-row">
          <span class="bar-label">MP</span>
          <div class="bar-bg"><div class="bar-fill mana" style="width:${manaPct * 100}%"></div></div>
          <span class="bar-value">${agent.mana}/${agent.max_mana}</span>
        </div>
      </div>
      <div class="card-stats">ATK:${agent.atk} MGK:${agent.mgk} SPD:${agent.spd} CON:${agent.con} HIT:${agent.hit}</div>
      ${actionText ? `<div class="card-action">${escHtml(actionText)}</div>` : ''}
    `;

    card.addEventListener('click', () => state.selectAgent(id));
    container.appendChild(card);
  }

  container.scrollTop = scrollTop;
}

// ===== Battle Log (bottom left) =====

function renderLog(state) {
  const container = document.getElementById('log-content');
  if (!container) return;

  const wasAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 30;

  container.innerHTML = '';

  for (const entry of state.eventLog) {
    const div = document.createElement('div');
    if (entry.actionType === 'commentary') {
      div.className = 'log-entry commentary';
      div.textContent = entry.description;
    } else {
      div.className = `log-entry ${entry.actionType || ''}`;
      div.innerHTML = `<span class="log-round">R${entry.round}</span>${escHtml(entry.description)}`;
    }
    container.appendChild(div);
  }

  if (wasAtBottom) {
    container.scrollTop = container.scrollHeight;
  }
}

// ===== Dialogue (bottom right) =====

function renderDialogue(state) {
  const container = document.getElementById('dialogue-content');
  if (!container) return;

  const wasAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 30;

  container.innerHTML = '';

  for (const entry of state.dialogueLog) {
    const div = document.createElement('div');
    div.className = 'dialogue-bubble';

    let shiftText = '';
    if (entry.dispositionShift > 0) shiftText = ` <span style="color:#3cb371">+${entry.dispositionShift.toFixed(2)}</span>`;
    else if (entry.dispositionShift < 0) shiftText = ` <span style="color:#e94560">${entry.dispositionShift.toFixed(2)}</span>`;

    div.innerHTML = `
      <div class="bubble-speaker">${escHtml(entry.speakerName)}</div>
      <div class="bubble-message">"${escHtml(entry.message)}"</div>
      ${shiftText ? `<div class="bubble-shift">${shiftText}</div>` : ''}
    `;
    container.appendChild(div);
  }

  if (wasAtBottom) {
    container.scrollTop = container.scrollHeight;
  }
}

// ===== Social (right panel, upper) =====

function renderSocial(state) {
  const container = document.getElementById('social-content');
  if (!container) return;

  container.innerHTML = '';

  // Show selected agent's relationships, or active agent's
  const agentId = state.selectedAgent || state.activeAgent;
  if (!agentId || !state.social[agentId]) {
    container.innerHTML = '<div style="color:var(--text-dim)">Select an agent</div>';
    return;
  }

  const agentName = state.agents[agentId]?.name || agentId;
  const header = document.createElement('div');
  header.style.cssText = 'font-weight:600;margin-bottom:6px;';
  header.textContent = `${agentName}'s Relationships`;
  container.appendChild(header);

  const rels = state.social[agentId];
  for (const [targetId, rel] of Object.entries(rels)) {
    const pair = document.createElement('div');
    pair.className = 'social-pair';

    const disp = rel.disposition;
    const barW = Math.abs(disp) * 30; // max 30px per side
    const isPos = disp >= 0;

    let badge = '';
    if (rel.alliance_declared) badge = '<span class="social-badge ally">ALLY</span>';
    else if (disp < -0.3) badge = '<span class="social-badge enemy">ENEMY</span>';

    pair.innerHTML = `
      <span style="width:50px;overflow:hidden;text-overflow:ellipsis">${escHtml(rel.agent_name)}</span>
      <div class="social-bar-bg">
        <div class="social-bar-fill ${isPos ? 'positive' : 'negative'}" style="width:${barW}px"></div>
      </div>
      <span style="width:36px;font-size:10px;color:${isPos ? '#3cb371' : '#e94560'}">${disp >= 0 ? '+' : ''}${disp.toFixed(2)}</span>
      ${badge}
    `;

    container.appendChild(pair);
  }
}

// ===== Cognitive (right panel, lower) =====

function renderCognitive(state) {
  const container = document.getElementById('cognitive-content');
  if (!container) return;

  container.innerHTML = '';

  const agentId = state.selectedAgent || state.activeAgent;
  if (!agentId) {
    container.innerHTML = '<div style="color:var(--text-dim)">Select an agent</div>';
    return;
  }

  const cog = state.cognitive[agentId];
  if (!cog) {
    container.innerHTML = '<div style="color:var(--text-dim)">No cognitive data yet</div>';
    return;
  }

  const agentName = state.agents[agentId]?.name || agentId;

  const sections = [
    { label: `${agentName}'s Mind`, value: '', cls: '' },
    { label: 'Memories', value: `${cog.memoryCount} nodes (imp: ${cog.importance.toFixed(0)})`, cls: '' },
    { label: 'Plan', value: cog.plan || 'No plan', cls: 'plan' },
    { label: 'Last Reflection', value: cog.reflection || 'None', cls: 'reflection' },
    { label: 'Reasoning', value: cog.reasoning || '...', cls: 'reasoning' },
  ];

  for (const sec of sections) {
    if (sec.label === sections[0].label) {
      const h = document.createElement('div');
      h.style.cssText = 'font-weight:600;margin-bottom:6px;';
      h.textContent = sec.value || sec.label;
      container.appendChild(h);
      continue;
    }
    const div = document.createElement('div');
    div.className = 'cog-section';
    div.innerHTML = `
      <div class="cog-label">${sec.label}</div>
      <div class="cog-value ${sec.cls}">${escHtml(sec.value)}</div>
    `;
    container.appendChild(div);
  }
}

// ===== Character Sheet (right panel, top) =====

function renderCharacterSheet(state) {
  const container = document.getElementById('character-content');
  if (!container) return;

  container.innerHTML = '';

  const agentId = state.selectedAgent || state.activeAgent;
  if (!agentId || !state.agents[agentId]) {
    container.innerHTML = '<div style="color:var(--text-dim)">Select an agent to view their character sheet</div>';
    return;
  }

  const agent = state.agents[agentId];

  // Name + class header
  const header = document.createElement('div');
  header.className = 'cs-header';
  header.innerHTML = `
    <div class="cs-name">${escHtml(agent.name)}</div>
    <div class="cs-class">${escHtml(agent.combat_class)}</div>
  `;
  container.appendChild(header);

  // Personality traits
  if (agent.personality && agent.personality.length > 0) {
    const traits = document.createElement('div');
    traits.className = 'cs-section';
    traits.innerHTML = `
      <div class="cs-label">Personality</div>
      <div class="cs-traits">${agent.personality.map(t => `<span class="cs-trait">${escHtml(t)}</span>`).join('')}</div>
    `;
    container.appendChild(traits);
  }

  // Backstory
  if (agent.backstory) {
    const backstory = document.createElement('div');
    backstory.className = 'cs-section';
    backstory.innerHTML = `
      <div class="cs-label">Backstory</div>
      <div class="cs-backstory">${escHtml(agent.backstory)}</div>
    `;
    container.appendChild(backstory);
  }

  // Stats
  const stats = document.createElement('div');
  stats.className = 'cs-section';
  const hpPct = agent.max_hp > 0 ? agent.hp / agent.max_hp : 0;
  const hpClass = hpPct > 0.6 ? 'hp' : hpPct > 0.3 ? 'hp warn' : 'hp crit';
  const manaPct = agent.max_mana > 0 ? agent.mana / agent.max_mana : 0;
  stats.innerHTML = `
    <div class="cs-label">Stats</div>
    <div class="cs-stats-grid">
      <div class="cs-stat-row">
        <span class="cs-stat-name">HP</span>
        <div class="bar-bg"><div class="bar-fill ${hpClass}" style="width:${hpPct * 100}%"></div></div>
        <span class="cs-stat-val">${agent.hp}/${agent.max_hp}</span>
      </div>
      <div class="cs-stat-row">
        <span class="cs-stat-name">MP</span>
        <div class="bar-bg"><div class="bar-fill mana" style="width:${manaPct * 100}%"></div></div>
        <span class="cs-stat-val">${agent.mana}/${agent.max_mana}</span>
      </div>
      <div class="cs-stats-inline">
        <span class="cs-stat-chip" title="Attack">ATK <b>${agent.atk}</b></span>
        <span class="cs-stat-chip" title="Magic">MGK <b>${agent.mgk}</b></span>
        <span class="cs-stat-chip" title="Speed">SPD <b>${agent.spd}</b></span>
        <span class="cs-stat-chip" title="Constitution">CON <b>${agent.con}</b></span>
        <span class="cs-stat-chip" title="Accuracy">HIT <b>${agent.hit}</b></span>
      </div>
      <div class="cs-stats-derived">
        <span title="Physical Defense">P.DEF: ${agent.phys_def}</span>
        <span title="Magical Defense">M.DEF: ${agent.mag_def}</span>
        <span title="Attack Range">Range: ${agent.attack_range}</span>
        <span title="Damage Type">Type: ${escHtml(agent.damage_type || 'physical')}</span>
      </div>
    </div>
  `;
  container.appendChild(stats);

  // Status effects
  if (agent.status_effects && agent.status_effects.length > 0) {
    const effects = document.createElement('div');
    effects.className = 'cs-section';
    effects.innerHTML = `
      <div class="cs-label">Status Effects</div>
      <div class="cs-effects">${agent.status_effects.map(e =>
        `<span class="cs-effect" title="Duration: ${e.duration} turns">${escHtml(e.type)} (${e.duration}t)</span>`
      ).join('')}</div>
    `;
    container.appendChild(effects);
  }

  // Abilities
  if (agent.abilities && agent.abilities.length > 0) {
    const abilitiesSection = document.createElement('div');
    abilitiesSection.className = 'cs-section';
    abilitiesSection.innerHTML = `<div class="cs-label">Abilities</div>`;

    for (const ab of agent.abilities) {
      const abDiv = document.createElement('div');
      abDiv.className = 'cs-ability';

      const onCd = ab.current_cd > 0;
      const cdText = onCd ? ` <span class="cs-ability-cd">CD: ${ab.current_cd}/${ab.cooldown}</span>` : '';

      let effectsHtml = '';
      if (ab.effects && ab.effects.length > 0) {
        effectsHtml = `<div class="cs-ability-effects">${ab.effects.map(eff => {
          const chanceStr = eff.chance < 1 ? ` (${Math.round(eff.chance * 100)}%)` : '';
          const magStr = eff.magnitude > 0 ? ` ${Math.round(eff.magnitude * 100)}%` : '';
          return `<span class="cs-ability-effect ${escHtml(eff.category)}">${escHtml(eff.type)}${magStr} ${eff.duration}t${chanceStr}</span>`;
        }).join('')}</div>`;
      }

      abDiv.innerHTML = `
        <div class="cs-ability-header">
          <span class="cs-ability-name${onCd ? ' on-cd' : ''}">${escHtml(ab.name)}</span>
          <span class="cs-ability-cost">${ab.mana_cost} MP</span>
          ${cdText}
        </div>
        <div class="cs-ability-meta">
          DMG: ${ab.damage} | Range: ${ab.range} | AoE: ${escHtml(ab.aoe_pattern)} | CD: ${ab.cooldown}
        </div>
        ${ab.description ? `<div class="cs-ability-desc">${escHtml(ab.description)}</div>` : ''}
        ${ab.tactical_hint ? `<div class="cs-ability-hint">${escHtml(ab.tactical_hint)}</div>` : ''}
        ${effectsHtml}
      `;
      abilitiesSection.appendChild(abDiv);
    }

    container.appendChild(abilitiesSection);
  }
}

// ===== Lore panel (right panel, top) =====

function renderLore(state) {
  const container = document.getElementById('lore-display');
  if (!container) return;

  if (!state.lore || !state.lore.world_description) {
    container.innerHTML = '';
    return;
  }

  // Only render once
  if (container.dataset.rendered === 'true') return;
  container.dataset.rendered = 'true';

  const lore = state.lore;
  let factsHtml = '';
  if (lore.key_facts && lore.key_facts.length > 0) {
    factsHtml = '<ul style="margin:4px 0 0 16px;padding:0">' +
      lore.key_facts.map(f => `<li>${escHtml(f)}</li>`).join('') + '</ul>';
  }

  container.innerHTML = `
    <div class="lore-panel">
      <div class="lore-panel-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">World Lore (click to toggle)</div>
      <div class="lore-panel-body">
        <p>${escHtml(lore.world_description)}</p>
        ${factsHtml}
      </div>
    </div>
  `;
}

// ===== Commentary (inline in battle log) =====

function renderCommentaryEntry(state) {
  // Called when a new commentary message arrives — appends to battle log
  const container = document.getElementById('log-content');
  if (!container) return;

  const latest = state.commentaryLog[state.commentaryLog.length - 1];
  if (!latest) return;

  const div = document.createElement('div');
  div.className = 'log-entry commentary';
  div.textContent = latest;

  container.appendChild(div);

  // Auto-scroll
  if (container.scrollHeight - container.scrollTop - container.clientHeight < 50) {
    container.scrollTop = container.scrollHeight;
  }
}

// ===== Helpers =====

function escHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function truncate(str, max) {
  if (!str) return '';
  return str.length > max ? str.slice(0, max) + '...' : str;
}
