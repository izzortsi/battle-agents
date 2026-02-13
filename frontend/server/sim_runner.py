"""SimRunner — event-emitting simulation loop with playback control.

Mirrors runner.py's _async_main() but injects event emission hooks
and play/pause/step controls via an asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

from combat.actions import ActionType, CombatAction
from combat.status_registry import get_behavior
from config_loader import (
    load_all_characters,
    load_balance_config,
    load_character_summaries,
    load_game_config,
    load_llm_config,
)
from frontend.server.serializers import (
    serialize_action_event,
    serialize_agent,
    serialize_cognitive,
    serialize_dialogue_exchange,
    serialize_snapshot,
    serialize_social,
)
from runner import pick_random_action, place_agents, setup_cognitive_loop
from world.battle_grid import BattleGrid
from world.environment import Environment

if TYPE_CHECKING:
    from frontend.server.app import ConnectionManager

log = logging.getLogger(__name__)


class SimRunner:
    """Manages the simulation lifecycle with WebSocket event emission."""

    def __init__(
        self,
        manager: ConnectionManager,
        *,
        use_random: bool = False,
        no_social: bool = False,
        max_chars: int | None = None,
    ) -> None:
        self._manager = manager
        self.control_queue: asyncio.Queue = asyncio.Queue()
        self._mode = "paused"  # paused | playing | stepping
        self._delay = 0.5  # seconds between events in play mode
        self._env: Environment | None = None
        self._cognitive_loop = None
        self._phase = "idle"
        self._started = False
        self._task: asyncio.Task | None = None
        # CLI options
        self._use_random = use_random
        self._no_social = no_social
        self._max_chars = max_chars
        # Persistent history for reconnecting clients
        self._event_log: list[dict] = []
        self._dialogue_log: list[dict] = []
        self._cognitive_states: dict[str, dict] = {}  # agent_id -> last cognitive
        # Landing page configuration (set via apply_configure before start)
        self._configure_data: dict | None = None
        # Lore + commentator state
        self._lore = None  # LoreContext
        self._commentator = None  # Commentator
        self._commentary_log: list[str] = []

    def apply_configure(self, msg: dict) -> None:
        """Store landing page configuration for use during _setup()."""
        self._configure_data = msg
        log.info(f"SimRunner: received configure — characters={msg.get('characters', 'all')}")

    async def start(self) -> None:
        """Start the simulation (called once from the WebSocket handler)."""
        if self._started:
            return
        self._started = True
        self._mode = "paused"
        self._task = asyncio.create_task(self._run())

    def get_snapshot(self) -> dict | None:
        if self._env is None:
            return None
        return serialize_snapshot(self._env, self._phase, self._cognitive_loop)

    def get_restore(self) -> dict | None:
        """Build a restore payload with snapshot + accumulated logs."""
        snapshot = self.get_snapshot()
        if snapshot is None:
            return None
        restore = {
            "type": "restore",
            "snapshot": snapshot,
            "event_log": self._event_log[-200:],
            "dialogue_log": self._dialogue_log[-100:],
            "cognitive": self._cognitive_states,
        }
        if self._lore:
            restore["lore"] = self._lore.to_dict()
        if self._commentary_log:
            restore["commentary_log"] = self._commentary_log[-50:]
        return restore

    def _record(self, data: dict) -> None:
        """Record a broadcast event for reconnect replay."""
        msg_type = data.get("type", "")
        if msg_type == "action":
            self._event_log.append({
                "description": data.get("description", ""),
                "action_type": data.get("action_type", ""),
                "agent_id": data.get("agent_id", ""),
                "round": self._env.turn_manager.round_number if self._env else 0,
                "success": data.get("success", True),
                "details": data.get("details", {}),
            })
        elif msg_type == "death":
            agent = self._env.agents.get(data.get("agent_id", "")) if self._env else None
            self._event_log.append({
                "description": f"{agent.name if agent else data.get('agent_id', '?')} has been slain!",
                "action_type": "death",
                "agent_id": data.get("agent_id", ""),
                "round": self._env.turn_manager.round_number if self._env else 0,
                "success": True,
                "details": {"killer_id": data.get("killer_id", "")},
            })
        elif msg_type == "victory":
            name = data.get("winner_name")
            rounds = data.get("rounds", 0)
            self._event_log.append({
                "description": f"VICTORY: {name} wins after {rounds} rounds!" if name else f"DRAW: No clear winner after {rounds} rounds.",
                "action_type": "victory",
                "round": self._env.turn_manager.round_number if self._env else 0,
                "success": True,
                "details": data,
            })
        elif msg_type == "dialogue":
            self._dialogue_log.append({
                "speaker": data.get("speaker", ""),
                "speaker_name": data.get("speaker_name", ""),
                "target": data.get("target", ""),
                "message": data.get("message", ""),
                "disposition_shift": data.get("disposition_shift", 0),
            })
        elif msg_type == "cognitive":
            self._cognitive_states[data.get("agent_id", "")] = {
                "memory_count": data.get("memory_count", 0),
                "importance": data.get("importance", 0),
                "plan": data.get("plan", ""),
                "reflection": data.get("reflection", ""),
                "reasoning": data.get("reasoning", ""),
            }
        elif msg_type == "commentary":
            text = data.get("text", "")
            self._commentary_log.append(text)
            # Also record in event_log so reconnect preserves interleaved order
            self._event_log.append({
                "description": text,
                "action_type": "commentary",
                "agent_id": "",
                "round": self._env.turn_manager.round_number if self._env else 0,
                "success": True,
                "details": {},
            })

    async def _broadcast(self, data: dict) -> None:
        self._record(data)
        await self._manager.broadcast(data)

    async def _await_advance(self) -> None:
        """Block until the user advances (step/play) or auto-play timer fires."""
        if self._mode == "stepping":
            self._mode = "paused"

        while True:
            if self._mode == "playing":
                # Auto-advance with delay, but still check for control messages
                try:
                    msg = await asyncio.wait_for(
                        self.control_queue.get(), timeout=self._delay
                    )
                    self._handle_control(msg)
                except asyncio.TimeoutError:
                    return  # delay elapsed, advance
            else:
                # Paused — wait for a control message
                msg = await self.control_queue.get()
                self._handle_control(msg)
                if self._mode in ("playing", "stepping"):
                    return

    def _handle_control(self, msg: dict) -> None:
        cmd = msg.get("type", "")
        if cmd == "step":
            self._mode = "stepping"
        elif cmd == "play":
            self._mode = "playing"
        elif cmd == "pause":
            self._mode = "paused"
        elif cmd == "speed":
            self._delay = msg.get("delay", 0.5)

    async def _drain_controls(self) -> None:
        """Process any pending control messages without blocking."""
        while not self.control_queue.empty():
            try:
                msg = self.control_queue.get_nowait()
                self._handle_control(msg)
            except asyncio.QueueEmpty:
                break

    async def _run(self) -> None:
        """Main simulation loop."""
        try:
            await self._setup()
            await self._broadcast(
                serialize_snapshot(self._env, self._phase, self._cognitive_loop)
            )

            # Wait for user to press play/step to begin
            await self._await_advance()

            # Generate lore if configured
            await self._generate_lore()

            game_cfg = load_game_config()
            pre_battle_cfg = game_cfg.get("pre_battle", {})
            pre_battle_enabled = (
                pre_battle_cfg.get("enabled", False)
                and not self._no_social
            )

            if pre_battle_enabled:
                await self._run_pre_battle(pre_battle_cfg)

            await self._run_combat()

        except Exception:
            log.exception("SimRunner crashed")

    async def _setup(self) -> None:
        """Initialize the simulation (mirrors runner.py main)."""
        game_cfg = load_game_config()
        load_balance_config(game_cfg)
        grid_cfg = game_cfg.get("grid", {})
        combat_cfg = game_cfg.get("combat", {})

        grid = BattleGrid(
            width=grid_cfg.get("width", 12),
            height=grid_cfg.get("height", 10),
        )
        self._env = Environment(
            grid=grid,
            perception_radius=combat_cfg.get("perception_radius", 8),
        )

        # Load characters — filter by landing page selection if configured
        agents = load_all_characters()
        if self._configure_data and self._configure_data.get("characters"):
            selected_ids = set(self._configure_data["characters"])
            agents = [a for a in agents if a.agent_id in selected_ids]
        elif self._max_chars and self._max_chars < len(agents):
            agents = agents[:self._max_chars]

        place_agents(agents, self._env)

        if not self._use_random:
            self._cognitive_loop, self._model_id = setup_cognitive_loop(game_cfg)

            # Apply model routing overrides from landing page
            if self._configure_data and self._configure_data.get("models"):
                self._apply_model_overrides(self._configure_data["models"])

            for agent in self._env.agents.values():
                self._cognitive_loop.register(agent)
        else:
            self._model_id = "random"

        self._phase = "setup"
        mode = "random" if self._use_random else ("no-social" if self._no_social else "full")
        log.info(f"SimRunner: loaded {len(agents)} agents, mode={mode}, model={self._model_id}")

    def _apply_model_overrides(self, models: dict) -> None:
        """Apply per-aspect model overrides from the landing page configure message."""
        if not self._cognitive_loop:
            return

        from runner import create_model_registry
        llm_cfg = load_llm_config()
        registry, _ = create_model_registry(llm_cfg)

        for role, adapter_key in models.items():
            if adapter_key and adapter_key in registry:
                self._cognitive_loop._routing[role] = registry.get(adapter_key)
                log.info(f"  Model override: {role} -> {adapter_key}")

    async def _generate_lore(self) -> None:
        """Generate world lore if a lore prompt is configured."""
        if self._use_random or not self._cognitive_loop:
            return

        lore_prompt = ""
        if self._configure_data:
            lore_prompt = self._configure_data.get("lore_prompt", "")

        # Always generate lore (with or without custom prompt)
        from cognition.lore import LoreContext, generate_lore, inject_lore_memories

        # Build character summaries for the lore generator
        char_summaries = []
        for agent in self._env.agents.values():
            char_summaries.append({
                "name": agent.identity.name,
                "combat_class": agent.identity.combat_class,
                "backstory": agent.identity.backstory,
                "personality_traits": agent.identity.personality_traits,
            })

        # Get the lore generation adapter
        lore_llm = self._cognitive_loop._get_llm("lore_generation")

        await self._broadcast({"type": "phase", "phase": "generating_lore"})

        self._lore = await asyncio.to_thread(
            generate_lore, char_summaries, lore_llm, lore_prompt
        )

        if self._lore and self._lore.world_description:
            # Inject lore into agent memories
            inject_lore_memories(
                self._lore,
                list(self._env.agents.values()),
                self._cognitive_loop,
            )

            # Set world lore on cognitive loop for decision prompts
            self._cognitive_loop.world_lore = self._lore.to_prompt_text()

            # Broadcast lore to frontend
            await self._broadcast({
                "type": "lore",
                **self._lore.to_dict(),
            })

            # Set up commentator with lore context
            self._setup_commentator()

            log.info(f"Lore generated and broadcast ({len(self._lore.raw_text)} chars)")
        else:
            # No lore — still set up commentator without lore
            self._setup_commentator()

    def _setup_commentator(self) -> None:
        """Initialize the commentator if a commentary model is configured."""
        if self._use_random or not self._cognitive_loop:
            return

        from cognition.commentator import Commentator

        commentary_llm = self._cognitive_loop._get_llm("commentary")
        lore_text = self._lore.to_prompt_text() if self._lore else ""
        self._commentator = Commentator(commentary_llm, lore_text=lore_text)

    async def _commentary(self, text: str) -> None:
        """Broadcast a commentary message if commentator generated text."""
        if text:
            await self._broadcast({"type": "commentary", "text": text})

    # ------------------------------------------------------------------ pre-battle

    async def _run_pre_battle(self, pre_battle_cfg: dict) -> None:
        self._phase = "pre_battle"
        await self._broadcast({"type": "phase", "phase": "pre_battle"})

        duration = pre_battle_cfg.get("duration_ticks", 6)
        pre_battle_radius = pre_battle_cfg.get("perception_radius", 12)
        original_radius = self._env.perception_engine.perception_radius
        self._env.perception_engine.perception_radius = pre_battle_radius

        agents = self._env.alive_agents()

        for tick in range(1, duration + 1):
            decisions = await self._cognitive_loop.async_run_pre_battle_tick(
                agents=agents,
                env=self._env,
                tick_number=tick,
                total_ticks=duration,
            )

            chatted_pairs: set[frozenset[str]] = set()

            for agent, decision in decisions:
                # Broadcast cognitive state
                cog = serialize_cognitive(agent.agent_id, self._cognitive_loop)
                cog["reasoning"] = decision.primary_action.reasoning
                await self._broadcast(cog)

                primary = decision.primary_action
                if primary.action_type == ActionType.MOVE:
                    result = self._env.resolve_action(primary)
                    event = serialize_action_event(primary, result, self._env)
                    await self._broadcast(event)
                elif primary.action_type == ActionType.WAIT:
                    pass  # no event needed for wait

                # Handle chat
                chat = decision.chat_action
                if chat and chat.target_agent:
                    pair = frozenset({agent.agent_id, chat.target_agent})
                    if pair not in chatted_pairs:
                        chatted_pairs.add(pair)
                        self._cognitive_loop.handle_pre_battle_chat(
                            initiator=agent, action=chat, env=self._env, tick_number=tick
                        )
                        # Broadcast dialogue event
                        init_state = self._cognitive_loop.get_state(agent.agent_id)
                        if init_state and init_state.memory._nodes:
                            last = init_state.memory._nodes[-1]
                            await self._broadcast({
                                "type": "dialogue",
                                "speaker": agent.agent_id,
                                "speaker_name": agent.name,
                                "target": chat.target_agent,
                                "message": chat.message or "",
                                "disposition_shift": 0,
                            })

                await self._await_advance()

            # Broadcast updated social state
            for agent in self._env.agents.values():
                social_data = serialize_social(agent)
                if social_data:
                    await self._broadcast({
                        "type": "social_update",
                        "agent_id": agent.agent_id,
                        "social": social_data,
                    })

            self._env.recent_actions.clear()

        self._env.perception_engine.perception_radius = original_radius

    # ------------------------------------------------------------------ combat

    async def _run_combat(self) -> None:
        self._phase = "combat"
        order = self._env.start_combat()
        await self._broadcast({
            "type": "phase",
            "phase": "combat",
            "turn_order": order,
        })
        await self._broadcast(
            serialize_snapshot(self._env, self._phase, self._cognitive_loop)
        )

        max_rounds = 50
        game_cfg = load_game_config()
        combat_cfg = game_cfg.get("combat", {})
        max_no_damage_rounds = combat_cfg.get("max_no_damage_rounds", 4)
        rounds_without_damage = 0
        damage_this_round = False

        while (
            not self._env.is_combat_over()
            and self._env.turn_manager.round_number <= max_rounds
        ):
            current = self._env.current_agent()
            if current is None or not current.is_alive:
                next_agent = self._env.advance_turn()
                if next_agent is None:
                    break
                continue

            round_num = self._env.turn_manager.round_number

            # Round start processing
            if self._env.turn_manager._current_idx == 0:
                if round_num > 1:
                    if not damage_this_round:
                        rounds_without_damage += 1
                    else:
                        rounds_without_damage = 0
                    damage_this_round = False

                    # End-of-round: mana regen, cooldowns, DoT
                    for a in self._env.alive_agents():
                        a.attributes.regen_mana()
                    for a in self._env.alive_agents():
                        a.attributes.tick_cooldowns()
                    for a in list(self._env.alive_agents()):
                        for eff in a.attributes.status_effects:
                            if get_behavior(eff.get("type", "")) == "damage_over_time":
                                mag = eff.get("magnitude", 0)
                                dot_dmg = int(mag * a.attributes.max_hp)
                                if dot_dmg > 0:
                                    a.attributes.take_damage(dot_dmg)
                                    damage_this_round = True
                                    if not a.is_alive:
                                        self._env.handle_agent_death(a.agent_id)
                                        await self._broadcast({
                                            "type": "death",
                                            "agent_id": a.agent_id,
                                            "killer_id": eff.get("source", ""),
                                        })
                                        break

                    # Bonus actions (LLM mode only)
                    if self._cognitive_loop and not self._env.is_combat_over():
                        for a in list(self._env.alive_agents()):
                            if a.attributes.spd >= 15:
                                chance = 10 + (a.attributes.spd - 15) * 2
                                if random.random() * 100 < chance:
                                    bonus_dec = await self._cognitive_loop.async_run_bonus_turn(
                                        a, self._env, round_num - 1
                                    )
                                    bonus_result = self._env.resolve_action(
                                        bonus_dec.primary_action
                                    )
                                    event = serialize_action_event(
                                        bonus_dec.primary_action, bonus_result, self._env
                                    )
                                    event["bonus"] = True
                                    await self._broadcast(event)

                                    # Commentary on bonus action
                                    if self._commentator:
                                        text = await asyncio.to_thread(
                                            self._commentator.comment_on_action,
                                            event.get("description", ""),
                                        )
                                        await self._commentary(text)

                                    if bonus_result.success and bonus_dec.primary_action.action_type == ActionType.ATTACK:
                                        damage_this_round = True
                                    if self._env.is_combat_over():
                                        break

            # Broadcast turn start
            await self._broadcast({
                "type": "turn_start",
                "agent_id": current.agent_id,
                "round": round_num,
            })

            # Tick status effects
            expired = current.attributes.tick_status_effects()

            # Skip-turn check
            skip = any(
                get_behavior(eff.get("type", "")) == "skip_turn"
                for eff in current.attributes.status_effects
            )
            if skip:
                await self._broadcast({
                    "type": "action",
                    "agent_id": current.agent_id,
                    "action_type": "wait",
                    "success": True,
                    "description": f"{current.name} is stunned and loses their turn!",
                    "details": {},
                    "state_delta": {current.agent_id: serialize_agent(current, self._env)},
                })
                self._env.advance_turn()
                await self._await_advance()
                continue

            if self._cognitive_loop:
                # LLM mode: cognitive turn
                urgency_text = ""
                if rounds_without_damage >= max_no_damage_rounds:
                    urgency_text = (
                        f"No damage has been dealt for {rounds_without_damage} rounds! "
                        f"The arena grows impatient. You MUST attack an enemy THIS TURN."
                    )

                decision = await self._cognitive_loop.async_run_turn(
                    current, self._env, round_num, urgency_text=urgency_text
                )

                # Broadcast cognitive state
                cog = serialize_cognitive(current.agent_id, self._cognitive_loop)
                cog["reasoning"] = decision.primary_action.reasoning
                await self._broadcast(cog)

                # Resolve primary action
                action = decision.primary_action
                result = self._env.resolve_action(action)
                event = serialize_action_event(action, result, self._env)
                await self._broadcast(event)

                # Commentary on action
                if self._commentator:
                    text = await asyncio.to_thread(
                        self._commentator.comment_on_action,
                        event.get("description", ""),
                    )
                    await self._commentary(text)

                if result.success and (
                    action.action_type == ActionType.ATTACK
                    or (
                        action.action_type == ActionType.ABILITY
                        and result.details.get("damage", 0) > 0
                    )
                ):
                    damage_this_round = True

                # Check for kills
                if result.details.get("killed"):
                    target_id = action.target_agent
                    await self._broadcast({
                        "type": "death",
                        "agent_id": target_id,
                        "killer_id": current.agent_id,
                    })
                    # Death commentary
                    if self._commentator and target_id:
                        victim = self._env.agents.get(target_id)
                        victim_name = victim.name if victim else target_id
                        text = await asyncio.to_thread(
                            self._commentator.comment_on_death,
                            victim_name,
                            current.name,
                        )
                        await self._commentary(text)

                # Handle chat
                if decision.chat_action and decision.chat_action.target_agent:
                    if self._cognitive_loop.can_chat_combat(current.agent_id, round_num):
                        self._cognitive_loop._handle_chat(
                            current, decision.chat_action, self._env, round_num
                        )
                        self._cognitive_loop.record_chat(current.agent_id, round_num)
                        await self._broadcast({
                            "type": "dialogue",
                            "speaker": current.agent_id,
                            "speaker_name": current.name,
                            "target": decision.chat_action.target_agent,
                            "message": decision.chat_action.message or "",
                            "disposition_shift": 0,
                        })
            else:
                # Random mode: pick a random action
                action = pick_random_action(current, self._env)
                result = self._env.resolve_action(action)
                event = serialize_action_event(action, result, self._env)
                await self._broadcast(event)

                if result.success and action.action_type == ActionType.ATTACK:
                    damage_this_round = True

                # Check for kills
                if result.details.get("killed"):
                    target_id = action.target_agent
                    await self._broadcast({
                        "type": "death",
                        "agent_id": target_id,
                        "killer_id": current.agent_id,
                    })

            self._env.advance_turn()

            # Wait for user advance
            await self._await_advance()

            # Drain any pending controls
            await self._drain_controls()

        # Victory
        winner = self._env.get_winner()
        self._phase = "victory"

        # Victory commentary
        if self._commentator and winner:
            text = await asyncio.to_thread(
                self._commentator.comment_on_victory,
                winner.name,
                winner.identity.combat_class,
                self._env.turn_manager.round_number,
            )
            await self._commentary(text)

        await self._broadcast({
            "type": "victory",
            "winner": winner.agent_id if winner else None,
            "winner_name": winner.name if winner else None,
            "rounds": self._env.turn_manager.round_number,
        })
