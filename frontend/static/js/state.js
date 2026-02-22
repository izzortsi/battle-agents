/**
 * state.js — Reactive state store for the simulation.
 */

class GameState {
  constructor() {
    this.grid = { width: 12, height: 10 };
    this.agents = {};        // agent_id -> agent data
    this.social = {};        // agent_id -> { target_id -> rel data }
    this.phase = 'idle';
    this.round = 0;
    this.activeAgent = null;
    this.turnOrder = [];
    this.eventLog = [];      // { description, actionType, round }
    this.dialogueLog = [];   // { speaker, speakerName, target, message, dispositionShift }
    this.dialogueSessions = []; // grouped conversation sessions
    this.cognitive = {};     // agent_id -> { memoryCount, importance, plan, reflection, reasoning }
    this.selectedAgent = null;
    this.lore = null;        // { world_description, key_facts, character_connections }
    this.commentaryLog = []; // [ string ]

    // Player input (set when backend emits awaiting_player)
    this.awaitingPlayer = null;      // { agentId, legalActions } | null
    this.playerMode = 'idle';        // idle | move | attack | ability
    this.selectedAbilityName = null; // name of ability pending target selection

    this._listeners = [];
  }

  onChange(fn) {
    this._listeners.push(fn);
  }

  notify(changeType, detail) {
    for (const fn of this._listeners) {
      fn(changeType, detail);
    }
  }

  applySnapshot(data) {
    this.grid = data.grid || this.grid;
    this.agents = data.agents || {};
    this.social = data.social || {};
    this.phase = data.phase || 'idle';
    this.round = data.round || 0;
    this.turnOrder = data.turn_order || [];
    this.activeAgent = data.active_agent || null;
    this.notify('snapshot');
  }

  applyRestore(data) {
    // Bulk restore: snapshot + logs + cognitive (no animations)
    const snap = data.snapshot;
    this.grid = snap.grid || this.grid;
    this.agents = snap.agents || {};
    this.social = snap.social || {};
    this.phase = snap.phase || 'idle';
    this.round = snap.round || 0;
    this.turnOrder = snap.turn_order || [];
    this.activeAgent = snap.active_agent || null;

    // Restore logs
    this.eventLog = (data.event_log || []).map(e => ({
      description: e.description,
      actionType: e.action_type,
      agentId: e.agent_id,
      round: e.round,
      success: e.success,
      details: e.details || {},
    }));
    this.dialogueLog = (data.dialogue_log || []).map(d => ({
      speaker: d.speaker,
      speakerName: d.speaker_name,
      target: d.target,
      message: d.message,
      dispositionShift: d.disposition_shift || 0,
    }));

    // Restore cognitive
    const cog = data.cognitive || {};
    for (const [agentId, c] of Object.entries(cog)) {
      this.cognitive[agentId] = {
        memoryCount: c.memory_count,
        importance: c.importance,
        plan: c.plan,
        reflection: c.reflection,
        reasoning: c.reasoning,
      };
    }

    // Restore dialogue sessions
    this.dialogueSessions = (data.dialogue_sessions || []).map(s => ({
      initiator: s.initiator,
      initiatorName: s.initiator_name,
      responder: s.responder,
      responderName: s.responder_name,
      exchanges: (s.exchanges || []).map(ex => ({
        speaker: ex.speaker,
        speakerName: ex.speaker_name,
        message: ex.message,
        dispositionShift: ex.disposition_shift || 0,
      })),
      summaries: s.summaries || {},
      status: s.status,
      exchangeCount: s.exchange_count || 0,
    }));

    // Restore lore + commentary
    if (data.lore) {
      this.lore = data.lore;
    }
    if (data.commentary_log) {
      this.commentaryLog = data.commentary_log;
    }

    this.notify('snapshot');  // triggers full re-render without animations
  }

  applyPhase(data) {
    this.phase = data.phase;
    if (data.turn_order) this.turnOrder = data.turn_order;
    this.notify('phase');
  }

  applySocialTick(data) {
    this.socialTick = data.tick;
    this.socialTickTotal = data.total;
    this.notify('social_tick', data);
  }

  applyTurnStart(data) {
    this.activeAgent = data.agent_id;
    this.round = data.round || this.round;
    this.notify('turn_start', data);
  }

  applyAction(event) {
    // Update agents from state_delta
    if (event.state_delta) {
      for (const [id, agentData] of Object.entries(event.state_delta)) {
        this.agents[id] = agentData;
      }
    }

    // Add to log
    this.eventLog.push({
      description: event.description,
      actionType: event.action_type,
      agentId: event.agent_id,
      round: this.round,
      success: event.success,
      details: event.details || {},
    });

    // Cap log at 200 entries
    if (this.eventLog.length > 200) {
      this.eventLog = this.eventLog.slice(-200);
    }

    // If we were awaiting player input for this same agent, clear it once
    // the authoritative action arrives.
    if (this.awaitingPlayer && event.agent_id === this.awaitingPlayer.agentId) {
      this.awaitingPlayer = null;
      this.playerMode = 'idle';
      this.selectedAbilityName = null;
    }

    this.notify('action', event);
  }

  applyDialogue(data) {
    this.dialogueLog.push({
      speaker: data.speaker,
      speakerName: data.speaker_name,
      target: data.target,
      message: data.message,
      dispositionShift: data.disposition_shift || 0,
    });

    if (this.dialogueLog.length > 100) {
      this.dialogueLog = this.dialogueLog.slice(-100);
    }

    this.notify('dialogue', data);
  }

  applyDialogueSession(data) {
    this.dialogueSessions.push({
      initiator: data.initiator,
      initiatorName: data.initiator_name,
      responder: data.responder,
      responderName: data.responder_name,
      exchanges: (data.exchanges || []).map(ex => ({
        speaker: ex.speaker,
        speakerName: ex.speaker_name,
        message: ex.message,
        dispositionShift: ex.disposition_shift || 0,
      })),
      summaries: data.summaries || {},
      status: data.status,
      exchangeCount: data.exchange_count || 0,
    });

    if (this.dialogueSessions.length > 50) {
      this.dialogueSessions = this.dialogueSessions.slice(-50);
    }

    this.notify('dialogue_session', data);
  }

  applyCognitive(data) {
    this.cognitive[data.agent_id] = {
      memoryCount: data.memory_count,
      importance: data.importance,
      plan: data.plan,
      reflection: data.reflection,
      reasoning: data.reasoning,
    };
    this.notify('cognitive', data);
  }

  applyDeath(data) {
    if (this.agents[data.agent_id]) {
      this.agents[data.agent_id].is_alive = false;
    }
    this.eventLog.push({
      description: `${this.agents[data.agent_id]?.name || data.agent_id} has been slain!`,
      actionType: 'death',
      agentId: data.agent_id,
      round: this.round,
      success: true,
      details: { killer_id: data.killer_id },
    });
    this.notify('death', data);
  }

  applyVictory(data) {
    this.phase = 'victory';
    this.victoryData = data;
    this.damageStats = null;      // will be filled by damage_stats message
    this.campaignUpdate = null;   // will be filled by campaign_update message
    this.eventLog.push({
      description: data.winner_name
        ? `VICTORY: ${data.winner_name} wins after ${data.rounds} rounds!`
        : `DRAW: No clear winner after ${data.rounds} rounds.`,
      actionType: 'victory',
      round: this.round,
      success: true,
      details: data,
    });
    this.notify('victory', data);
  }

  applyDamageStats(data) {
    this.damageStats = data.stats || [];
    this.notify('damage_stats', data);
  }

  applyCampaignUpdate(data) {
    this.campaignUpdate = data;
    this.notify('campaign_update', data);
  }

  applySocialUpdate(data) {
    this.social[data.agent_id] = data.social;
    this.notify('social_update', data);
  }

  applyLore(data) {
    this.lore = {
      world_description: data.world_description || '',
      key_facts: data.key_facts || [],
      character_connections: data.character_connections || [],
    };
    this.notify('lore', data);
  }

  applyCommentary(data) {
    this.commentaryLog.push(data.text);
    if (this.commentaryLog.length > 50) {
      this.commentaryLog = this.commentaryLog.slice(-50);
    }
    // Also add to eventLog so renderLog includes commentary on re-render
    this.eventLog.push({
      description: data.text,
      actionType: 'commentary',
      agentId: '',
      round: this.round,
      success: true,
      details: {},
    });
    this.notify('commentary', data);
  }

  applyAwaitingPlayer(data) {
    this.awaitingPlayer = {
      agentId: data.agent_id,
      legalActions: data.legal_actions || {},
    };
    this.playerMode = 'idle';
    this.selectedAbilityName = null;
    this.notify('awaiting_player', data);
  }

  selectAgent(agentId) {
    this.selectedAgent = agentId;
    this.notify('select', { agent_id: agentId });
  }
}
