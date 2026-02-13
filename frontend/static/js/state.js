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
    this.cognitive = {};     // agent_id -> { memoryCount, importance, plan, reflection, reasoning }
    this.selectedAgent = null;
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

    this.notify('snapshot');  // triggers full re-render without animations
  }

  applyPhase(data) {
    this.phase = data.phase;
    if (data.turn_order) this.turnOrder = data.turn_order;
    this.notify('phase');
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

  applySocialUpdate(data) {
    this.social[data.agent_id] = data.social;
    this.notify('social_update', data);
  }

  selectAgent(agentId) {
    this.selectedAgent = agentId;
    this.notify('select', { agent_id: agentId });
  }
}
