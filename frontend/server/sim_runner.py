"""SimRunner — event-emitting simulation loop with playback control.

Mirrors runner.py's _async_main() but injects event emission hooks
and play/pause/step controls via an asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from typing import TYPE_CHECKING

from combat.actions import ActionType, CombatAction, make_wait
from cognition.decision import CombatDecision
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
        auto_play: bool = False,
        on_victory: Callable[[], None] | None = None,
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
        # Spectator / auto-play options
        self._auto_play = auto_play
        self._on_victory = on_victory
        # Persistent history for reconnecting clients
        self._event_log: list[dict] = []
        self._dialogue_log: list[dict] = []
        self._dialogue_sessions: list[dict] = []
        self._cognitive_states: dict[str, dict] = {}  # agent_id -> last cognitive
        # Landing page configuration (set via apply_configure before start)
        self._configure_data: dict | None = None
        # Lore + commentator state
        self._lore = None  # LoreContext
        self._commentator = None  # Commentator
        self._commentary_log: list[str] = []
        # Campaign state (set during _setup if campaign_id in configure_data)
        self._campaign_mgr = None  # CampaignManager | None
        self._campaign_db = None  # CampaignDB | None

    def apply_configure(self, msg: dict) -> None:
        """Store landing page configuration for use during _setup()."""
        self._configure_data = msg
        log.info(
            f"SimRunner: received configure — characters={msg.get('characters', 'all')}"
        )

    async def start(self) -> None:
        """Start the simulation (called once from the WebSocket handler)."""
        if self._started:
            log.warning(
                "SimRunner.start() called but already started (phase=%s)", self._phase
            )
            return
        self._started = True
        self._mode = "playing" if self._auto_play else "paused"
        log.info("SimRunner: starting simulation (mode=%s)", self._mode)
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
            "dialogue_sessions": self._dialogue_sessions[-50:],
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
            self._event_log.append(
                {
                    "description": data.get("description", ""),
                    "action_type": data.get("action_type", ""),
                    "agent_id": data.get("agent_id", ""),
                    "round": self._env.turn_manager.round_number if self._env else 0,
                    "success": data.get("success", True),
                    "details": data.get("details", {}),
                }
            )
        elif msg_type == "death":
            agent = (
                self._env.agents.get(data.get("agent_id", "")) if self._env else None
            )
            self._event_log.append(
                {
                    "description": f"{agent.name if agent else data.get('agent_id', '?')} has been slain!",
                    "action_type": "death",
                    "agent_id": data.get("agent_id", ""),
                    "round": self._env.turn_manager.round_number if self._env else 0,
                    "success": True,
                    "details": {"killer_id": data.get("killer_id", "")},
                }
            )
        elif msg_type == "victory":
            name = data.get("winner_name")
            rounds = data.get("rounds", 0)
            is_alliance = data.get("alliance_victory", False)
            if is_alliance:
                desc = f"ALLIANCE VICTORY: {name} win together after {rounds} rounds!"
            elif name:
                desc = f"VICTORY: {name} wins after {rounds} rounds!"
            else:
                desc = f"DRAW: No clear winner after {rounds} rounds."
            self._event_log.append(
                {
                    "description": desc,
                    "action_type": "victory",
                    "round": self._env.turn_manager.round_number if self._env else 0,
                    "success": True,
                    "details": data,
                }
            )
        elif msg_type == "dialogue":
            self._dialogue_log.append(
                {
                    "speaker": data.get("speaker", ""),
                    "speaker_name": data.get("speaker_name", ""),
                    "target": data.get("target", ""),
                    "message": data.get("message", ""),
                    "disposition_shift": data.get("disposition_shift", 0),
                }
            )
        elif msg_type == "cognitive":
            self._cognitive_states[data.get("agent_id", "")] = {
                "memory_count": data.get("memory_count", 0),
                "importance": data.get("importance", 0),
                "plan": data.get("plan", ""),
                "reflection": data.get("reflection", ""),
                "reasoning": data.get("reasoning", ""),
            }
        elif msg_type == "dialogue_session":
            self._dialogue_sessions.append(data)
        elif msg_type == "commentary":
            text = data.get("text", "")
            self._commentary_log.append(text)
            # Also record in event_log so reconnect preserves interleaved order
            self._event_log.append(
                {
                    "description": text,
                    "action_type": "commentary",
                    "agent_id": "",
                    "round": self._env.turn_manager.round_number if self._env else 0,
                    "success": True,
                    "details": {},
                }
            )

    @staticmethod
    def _serialize_dialogue_session(session, initiator, responder) -> dict:
        """Serialize a DialogueSession into a WebSocket event."""
        return {
            "type": "dialogue_session",
            "initiator": session.initiator,
            "initiator_name": initiator.name if initiator else session.initiator,
            "responder": session.responder,
            "responder_name": responder.name if responder else session.responder,
            "exchanges": [
                {
                    "speaker": ex.speaker,
                    "speaker_name": ex.speaker_name,
                    "message": ex.message,
                    "disposition_shift": ex.disposition_shift,
                }
                for ex in session.exchanges
            ],
            "summaries": session.summaries or {},
            "status": session.status,
            "exchange_count": len(session.exchanges),
        }

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

            # Wait for user to press play/step to begin (skip in auto-play)
            if not self._auto_play:
                await self._await_advance()

            # Generate lore if configured
            await self._generate_lore()

            game_cfg = load_game_config()
            pre_battle_cfg = game_cfg.get("pre_battle", {})
            pre_battle_enabled = (
                pre_battle_cfg.get("enabled", False) and not self._no_social
            )

            if pre_battle_enabled:
                await self._run_pre_battle(pre_battle_cfg)

            # Transition from tavern to combat arena if needed
            if self._tavern_env is not None:
                agents = list(self._tavern_env.agents.values())
                place_agents(agents, self._combat_env)
                self._env = self._combat_env
                self._tavern_env = None  # allow GC of tavern environment

                # Broadcast transition snapshot so the frontend rebuilds the grid
                await self._broadcast(
                    serialize_snapshot(self._env, "combat", self._cognitive_loop)
                )

            await self._run_combat()

        except Exception:
            log.exception("SimRunner crashed")
            self._phase = "crashed"
            # Notify caller so spectator mode can restart after crashes
            if self._on_victory:
                self._on_victory()

    async def _setup(self) -> None:
        """Initialize the simulation (mirrors runner.py main)."""
        game_cfg = load_game_config()
        self._game_cfg = game_cfg
        load_balance_config(game_cfg)
        grid_cfg = game_cfg.get("grid", {})
        combat_cfg = game_cfg.get("combat", {})

        pre_battle_cfg = game_cfg.get("pre_battle", {})
        pre_battle_map = pre_battle_cfg.get("map", "arena")
        victory_cfg = game_cfg.get("victory", {})
        victory_mode = victory_cfg.get("mode", "last_standing")

        # Combat grid (always created)
        combat_grid = BattleGrid.create_arena(
            width=grid_cfg.get("width", 12),
            height=grid_cfg.get("height", 10),
        )
        self._combat_env = Environment(
            grid=combat_grid,
            perception_radius=combat_cfg.get("perception_radius", 8),
            victory_mode=victory_mode,
        )

        # Tavern grid for pre-battle (if configured)
        use_tavern = (
            pre_battle_cfg.get("enabled", False)
            and not self._no_social
            and pre_battle_map == "tavern"
        )
        if use_tavern:
            tavern_grid = BattleGrid.create_tavern()
            self._env = Environment(
                grid=tavern_grid,
                perception_radius=pre_battle_cfg.get("perception_radius", 12),
                victory_mode=victory_mode,
            )
            self._tavern_env = self._env
        else:
            self._env = self._combat_env
            self._tavern_env = None

        # Load characters — campaign roster or landing page selection
        campaign_id = (
            self._configure_data.get("campaign_id") if self._configure_data else None
        )
        if campaign_id:
            from campaign.persistence import CampaignDB
            from campaign.manager import CampaignManager

            self._campaign_db = CampaignDB()
            self._campaign_mgr = CampaignManager(self._campaign_db, campaign_id)
            agents = self._campaign_mgr.build_agents()
            log.info(
                f"SimRunner: campaign mode (id={campaign_id}, "
                f"{len(agents)} alive agents)"
            )
        else:
            agents = load_all_characters()
            if self._configure_data and self._configure_data.get("characters"):
                selected_ids = set(self._configure_data["characters"])
                agents = [a for a in agents if a.agent_id in selected_ids]
            elif self._max_chars and self._max_chars < len(agents):
                agents = agents[: self._max_chars]

        # Apply sprite overrides from landing page before placing
        if self._configure_data and self._configure_data.get("sprites"):
            sprite_map = self._configure_data["sprites"]
            for agent in agents:
                if agent.agent_id in sprite_map:
                    agent.identity.sprite = sprite_map[agent.agent_id]
                    log.info(
                        f"  Sprite override: {agent.name} -> {sprite_map[agent.agent_id]}"
                    )

        if use_tavern:
            place_agents(agents, self._env, min_dist=2)
        else:
            place_agents(agents, self._env)

        if not self._use_random:
            self._cognitive_loop, self._model_id = setup_cognitive_loop(game_cfg)

            # Apply model routing overrides from landing page
            if self._configure_data and self._configure_data.get("models"):
                self._apply_model_overrides(self._configure_data["models"])

            for agent in self._env.agents.values():
                self._cognitive_loop.register(agent)

            # Restore campaign memories + social relationships
            if self._campaign_mgr:
                self._campaign_mgr.restore_agent_state(
                    list(self._env.agents.values()), self._cognitive_loop
                )
        else:
            self._model_id = "random"

        self._phase = "setup"
        mode = (
            "random"
            if self._use_random
            else ("no-social" if self._no_social else "full")
        )
        log.info(
            f"SimRunner: loaded {len(agents)} agents, mode={mode}, model={self._model_id}"
        )

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
        """Generate world lore, or load persisted lore for campaigns."""
        if self._use_random or not self._cognitive_loop:
            return

        from cognition.lore import LoreContext, generate_lore, inject_lore_memories

        # Campaign mode: try to load persisted lore first
        if self._campaign_db and self._campaign_mgr:
            saved = self._campaign_db.load_lore(self._campaign_mgr.campaign_id)
            if saved:
                self._lore = LoreContext(
                    world_description=saved.get("world_description", ""),
                    key_facts=saved.get("key_facts", []),
                    character_connections=saved.get("character_connections", []),
                    raw_text=saved.get("raw_text", ""),
                )
                log.info(
                    "Campaign lore loaded from DB (%d chars)", len(self._lore.raw_text)
                )

        # Generate lore if we don't have any yet
        if not self._lore or not self._lore.world_description:
            lore_prompt = ""
            if self._configure_data:
                lore_prompt = self._configure_data.get("lore_prompt", "")

            # Build character summaries for the lore generator
            char_summaries = []
            for agent in self._env.agents.values():
                char_summaries.append(
                    {
                        "name": agent.identity.name,
                        "combat_class": agent.identity.combat_class,
                        "backstory": agent.identity.backstory,
                        "personality_traits": agent.identity.personality_traits,
                    }
                )

            lore_llm = self._cognitive_loop._get_llm("lore_generation")

            await self._broadcast({"type": "phase", "phase": "generating_lore"})

            self._lore = await asyncio.to_thread(
                generate_lore, char_summaries, lore_llm, lore_prompt
            )

            # Persist lore for campaign reuse
            if (
                self._lore
                and self._lore.world_description
                and self._campaign_db
                and self._campaign_mgr
            ):
                lore_save = self._lore.to_dict()
                lore_save["raw_text"] = self._lore.raw_text
                self._campaign_db.save_lore(self._campaign_mgr.campaign_id, lore_save)
                log.info("Campaign lore saved to DB")

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
            await self._broadcast(
                {
                    "type": "lore",
                    **self._lore.to_dict(),
                }
            )

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

        # Chat distance limits for pre-battle (intimate tavern conversations)
        self._env.chat_speak_radius = pre_battle_cfg.get("chat_speak_radius", 4)
        self._env.chat_listen_radius = pre_battle_cfg.get("chat_listen_radius", 12)

        agents = self._env.alive_agents()

        for tick in range(1, duration + 1):
            await self._broadcast(
                {"type": "social_tick", "tick": tick, "total": duration}
            )
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
                        session = await asyncio.to_thread(
                            self._cognitive_loop.handle_pre_battle_chat,
                            agent,
                            chat,
                            self._env,
                            tick,
                        )
                        if session:
                            for ex in session.exchanges:
                                target_id = (
                                    chat.target_agent
                                    if ex.speaker == agent.agent_id
                                    else agent.agent_id
                                )
                                await self._broadcast(
                                    {
                                        "type": "dialogue",
                                        "speaker": ex.speaker,
                                        "speaker_name": ex.speaker_name,
                                        "target": target_id,
                                        "message": ex.message,
                                        "disposition_shift": ex.disposition_shift,
                                    }
                                )
                            # Broadcast the complete session envelope
                            resp_agent = self._env.agents.get(chat.target_agent)
                            await self._broadcast(
                                self._serialize_dialogue_session(
                                    session, agent, resp_agent
                                )
                            )

                await self._await_advance()

            # Broadcast updated social state
            for agent in self._env.agents.values():
                social_data = serialize_social(agent)
                if social_data:
                    await self._broadcast(
                        {
                            "type": "social_update",
                            "agent_id": agent.agent_id,
                            "social": social_data,
                        }
                    )

            self._env.recent_actions.clear()

        self._env.perception_engine.perception_radius = original_radius

    # ------------------------------------------------------------------ combat

    async def _run_combat(self) -> None:
        self._phase = "combat"
        # Set combat chat radii (yelling distance)
        combat_cfg = self._game_cfg.get("combat", {})
        self._env.chat_speak_radius = combat_cfg.get("chat_speak_radius", 8)
        self._env.chat_listen_radius = combat_cfg.get("chat_listen_radius", 12)
        order = self._env.start_combat()
        await self._broadcast(
            {
                "type": "phase",
                "phase": "combat",
                "turn_order": order,
            }
        )
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
                                        dot_type = eff.get("type", "DoT")
                                        dot_src = eff.get("source", "unknown")
                                        self._env.handle_agent_death(
                                            a.agent_id,
                                            killer=(
                                                self._env.agents[dot_src].name
                                                if dot_src in self._env.agents
                                                else dot_src
                                            ),
                                            method=f"{dot_type} damage",
                                            round_num=self._env.turn_manager.global_turn,
                                        )
                                        await self._broadcast(
                                            {
                                                "type": "death",
                                                "agent_id": a.agent_id,
                                                "killer_id": eff.get("source", ""),
                                            }
                                        )
                                        break

                    # Bonus actions (LLM mode only)
                    if self._cognitive_loop and not self._env.is_combat_over():
                        for a in list(self._env.alive_agents()):
                            if a.attributes.spd >= 15:
                                chance = 10 + (a.attributes.spd - 15) * 2
                                if random.random() * 100 < chance:
                                    bonus_dec = (
                                        await self._cognitive_loop.async_run_bonus_turn(
                                            a, self._env, round_num - 1
                                        )
                                    )

                                    # Resolve bonus move (before or after)
                                    async def _resolve_bonus_move():
                                        if bonus_dec.move_action:
                                            bmr = self._env.resolve_action(
                                                bonus_dec.move_action
                                            )
                                            if bmr.success:
                                                bme = serialize_action_event(
                                                    bonus_dec.move_action,
                                                    bmr,
                                                    self._env,
                                                )
                                                bme["bonus"] = True
                                                await self._broadcast(bme)

                                    if not bonus_dec.move_after:
                                        await _resolve_bonus_move()
                                    bonus_result = self._env.resolve_action(
                                        bonus_dec.primary_action
                                    )
                                    event = serialize_action_event(
                                        bonus_dec.primary_action,
                                        bonus_result,
                                        self._env,
                                    )
                                    event["bonus"] = True
                                    await self._broadcast(event)
                                    if bonus_dec.move_after:
                                        await _resolve_bonus_move()

                                    # Commentary on bonus action
                                    if self._commentator:
                                        text = await asyncio.to_thread(
                                            self._commentator.comment_on_action,
                                            event.get("description", ""),
                                        )
                                        await self._commentary(text)

                                    if (
                                        bonus_result.success
                                        and bonus_dec.primary_action.action_type
                                        == ActionType.ATTACK
                                    ):
                                        damage_this_round = True
                                    if self._env.is_combat_over():
                                        break

            # Broadcast turn start
            await self._broadcast(
                {
                    "type": "turn_start",
                    "agent_id": current.agent_id,
                    "round": round_num,
                }
            )

            # Tick status effects
            expired = current.attributes.tick_status_effects()

            # Skip-turn check
            skip = any(
                get_behavior(eff.get("type", "")) == "skip_turn"
                for eff in current.attributes.status_effects
            )
            if skip:
                await self._broadcast(
                    {
                        "type": "action",
                        "agent_id": current.agent_id,
                        "action_type": "wait",
                        "success": True,
                        "description": f"{current.name} is stunned and loses their turn!",
                        "details": {},
                        "state_delta": {
                            current.agent_id: serialize_agent(current, self._env)
                        },
                    }
                )
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

                # Resolve optional move (before or after primary)
                async def _resolve_move():
                    if decision.move_action:
                        move_result = self._env.resolve_action(decision.move_action)
                        if move_result.success:
                            move_event = serialize_action_event(
                                decision.move_action, move_result, self._env
                            )
                            await self._broadcast(move_event)
                        else:
                            log.warning(
                                f"  {current.name}: move failed — {move_result.description}"
                            )

                if not decision.move_after:
                    await _resolve_move()

                # Resolve primary action with retry on invalid actions
                max_retries = 4
                action = decision.primary_action
                result = self._env.resolve_action(action)

                retry_count = 0
                while not result.success and retry_count < max_retries:
                    retry_count += 1
                    log.info(
                        f"  {current.name}: invalid action ({result.description}), "
                        f"retry {retry_count}/{max_retries}"
                    )
                    decision = await self._cognitive_loop.async_retry_decide(
                        current,
                        self._env,
                        round_num,
                        error_feedback=result.description,
                        urgency_text=urgency_text,
                    )
                    # Resolve the retry's move (before primary) so the agent
                    # can reposition before re-attempting the primary action.
                    if decision.move_action and not decision.move_after:
                        mr = self._env.resolve_action(decision.move_action)
                        if mr.success:
                            move_event = serialize_action_event(
                                decision.move_action, mr, self._env
                            )
                            await self._broadcast(move_event)
                        else:
                            log.warning(
                                f"  {current.name}: retry move failed — {mr.description}"
                            )
                    action = decision.primary_action
                    result = self._env.resolve_action(action)

                if not result.success and retry_count >= max_retries:
                    # Final fallback: force WAIT
                    log.warning(
                        f"  {current.name}: all retries exhausted, forcing WAIT"
                    )
                    action = make_wait(
                        current.agent_id, "retries exhausted — forced wait"
                    )
                    result = self._env.resolve_action(action)
                    decision = CombatDecision(
                        primary_action=action,
                        chat_action=decision.chat_action,
                    )

                # Broadcast cognitive state
                cog = serialize_cognitive(current.agent_id, self._cognitive_loop)
                cog["reasoning"] = decision.primary_action.reasoning
                await self._broadcast(cog)

                event = serialize_action_event(action, result, self._env)
                await self._broadcast(event)

                if decision.move_after:
                    await _resolve_move()

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
                    await self._broadcast(
                        {
                            "type": "death",
                            "agent_id": target_id,
                            "killer_id": current.agent_id,
                        }
                    )
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
                    if self._cognitive_loop.can_chat_combat(
                        current.agent_id, round_num
                    ):
                        session = await asyncio.to_thread(
                            self._cognitive_loop._handle_chat,
                            current,
                            decision.chat_action,
                            self._env,
                            round_num,
                        )
                        self._cognitive_loop.record_chat(current.agent_id, round_num)
                        if session:
                            for ex in session.exchanges:
                                target_id = (
                                    decision.chat_action.target_agent
                                    if ex.speaker == current.agent_id
                                    else current.agent_id
                                )
                                await self._broadcast(
                                    {
                                        "type": "dialogue",
                                        "speaker": ex.speaker,
                                        "speaker_name": ex.speaker_name,
                                        "target": target_id,
                                        "message": ex.message,
                                        "disposition_shift": ex.disposition_shift,
                                    }
                                )
                            # Broadcast the complete session envelope
                            resp_agent = self._env.agents.get(
                                decision.chat_action.target_agent
                            )
                            await self._broadcast(
                                self._serialize_dialogue_session(
                                    session, current, resp_agent
                                )
                            )
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
                    await self._broadcast(
                        {
                            "type": "death",
                            "agent_id": target_id,
                            "killer_id": current.agent_id,
                        }
                    )

            self._env.advance_turn()

            # Wait for user advance
            await self._await_advance()

            # Drain any pending controls
            await self._drain_controls()

        # Victory
        winner = self._env.get_winner()
        winners = self._env.get_winners()
        self._phase = "victory"

        # Victory commentary
        if self._commentator and (winner or len(winners) > 1):
            if len(winners) > 1:
                names = ", ".join(w.name for w in winners)
                text = await asyncio.to_thread(
                    self._commentator.comment_on_victory,
                    names,
                    "alliance",
                    self._env.turn_manager.round_number,
                )
            else:
                text = await asyncio.to_thread(
                    self._commentator.comment_on_victory,
                    winner.name,
                    winner.identity.combat_class,
                    self._env.turn_manager.round_number,
                )
            await self._commentary(text)

        if len(winners) > 1:
            winner_ids = [w.agent_id for w in winners]
            winner_names = [w.name for w in winners]
            await self._broadcast(
                {
                    "type": "victory",
                    "winner": winner_ids[0],
                    "winner_name": ", ".join(winner_names),
                    "winners": winner_ids,
                    "winner_names": winner_names,
                    "alliance_victory": True,
                    "rounds": self._env.turn_manager.round_number,
                }
            )
        else:
            await self._broadcast(
                {
                    "type": "victory",
                    "winner": winner.agent_id if winner else None,
                    "winner_name": winner.name if winner else None,
                    "rounds": self._env.turn_manager.round_number,
                }
            )

        # Broadcast damage stats (all modes)
        damage_stats = []
        for aid, dmg in sorted(self._env.damage_dealt.items(), key=lambda x: -x[1]):
            agent = self._env.agents.get(aid)
            damage_stats.append(
                {
                    "agent_id": aid,
                    "name": agent.name if agent else aid,
                    "damage": dmg,
                }
            )
        if damage_stats:
            await self._broadcast({"type": "damage_stats", "stats": damage_stats})

        # Campaign post-battle processing
        if self._campaign_mgr and self._cognitive_loop:
            try:
                from runner import create_adapter
                from config_loader import load_llm_config

                llm_cfg = load_llm_config()
                adapter, _ = create_adapter(llm_cfg)
                record = self._campaign_mgr.process_battle_results(
                    self._env,
                    self._cognitive_loop,
                    adapter,
                )

                # Build campaign update event
                roster = self._campaign_mgr.get_roster()
                level_ups = []
                for r in roster:
                    if r.alive and r.level > 1:
                        # Check if levelled this battle by comparing XP
                        xp_gained = record.xp_awards.get(r.agent_id, 0)
                        if xp_gained > 0:
                            level_ups.append(
                                {
                                    "agent_id": r.agent_id,
                                    "name": r.name,
                                    "level": r.level,
                                }
                            )

                await self._broadcast(
                    {
                        "type": "campaign_update",
                        "campaign_id": self._campaign_mgr.campaign_id,
                        "battle_num": record.battle_num,
                        "xp_awards": record.xp_awards,
                        "deaths": record.death_ids,
                        "level_ups": level_ups,
                        "roster": [
                            {
                                "agent_id": r.agent_id,
                                "name": r.name,
                                "combat_class": r.combat_class,
                                "sprite": r.sprite,
                                "alive": r.alive,
                                "level": r.level,
                                "xp": r.xp,
                                "xp_to_next": r.xp_to_next_level,
                                "atk": r.atk,
                                "mgk": r.mgk,
                                "spd": r.spd,
                                "con": r.con,
                                "hit": r.hit,
                            }
                            for r in roster
                        ],
                    }
                )
                log.info(f"Campaign update broadcast: battle #{record.battle_num}")
            except Exception:
                log.error("Campaign post-battle processing failed.", exc_info=True)
            finally:
                if self._campaign_db:
                    self._campaign_db.close()
                    self._campaign_db = None

        # Notify caller that the battle is over (spectator auto-restart)
        if self._on_victory:
            self._on_victory()
