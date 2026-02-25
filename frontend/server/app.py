"""FastAPI application — serves the frontend and manages WebSocket connections."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import socket
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Spectator mode — auto-start, auto-play, auto-restart battles
SPECTATOR_MODE = os.environ.get("SPECTATOR_MODE", "").lower() in ("1", "true")


@asynccontextmanager
async def lifespan(app_instance):
    if SPECTATOR_MODE:
        global _sim_options
        _sim_options = {"use_random": False, "no_social": False, "max_chars": None}
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        log.info("Battle-Agents spectator mode — auto-starting battle")
        asyncio.create_task(_start_spectator_battle())
    yield


app = FastAPI(title="Battle-Agents", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# CLI options — populated by main(), read by _get_or_create_runner()
_sim_options: dict = {}


class ConnectionManager:
    """Tracks active WebSocket connections and broadcasts events."""

    def __init__(self) -> None:
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)
        log.info(f"WebSocket connected ({len(self.active)} active)")

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.active:
            self.active.remove(ws)
        log.info(f"WebSocket disconnected ({len(self.active)} active)")

    async def broadcast(self, data: dict) -> None:
        """Send JSON data to all connected clients."""
        text = json.dumps(data)
        dead: list[WebSocket] = []
        for ws in self.active:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()

# Lazy-initialised SimRunner (created on first "start" command)
_runner = None
_runner_lock = asyncio.Lock()


async def _get_or_create_runner():
    """Create the SimRunner on first use, or replace it if the previous battle finished."""
    global _runner
    async with _runner_lock:
        if _runner is not None and _runner._phase in ("victory", "crashed"):
            log.info(
                "Replacing finished runner (phase=%s) with a fresh one", _runner._phase
            )
            _runner = None
        if _runner is None:
            from frontend.server.sim_runner import SimRunner

            _runner = SimRunner(manager, **_sim_options)
            log.info("Created new SimRunner")
        return _runner


# ================================================================
# Spectator mode — auto-start / auto-restart
# ================================================================


async def _start_spectator_battle():
    """Create a new SimRunner with random 4-6 characters and auto-play."""
    global _runner
    num_chars = random.randint(4, 6)
    async with _runner_lock:
        from frontend.server.sim_runner import SimRunner

        _runner = SimRunner(
            manager,
            auto_play=True,
            on_victory=_on_battle_complete,
            max_chars=num_chars,
        )
    log.info(f"Spectator: starting battle with {num_chars} characters")
    await _runner.start()


def _on_battle_complete():
    """Called by SimRunner after victory or crash. Schedules restart."""
    asyncio.create_task(_restart_after_delay())


async def _restart_after_delay():
    """Wait 30s, then start a fresh battle."""
    global _runner
    await manager.broadcast({"type": "phase", "phase": "restarting"})
    log.info("Battle complete — next battle in 30s")
    await asyncio.sleep(30)
    async with _runner_lock:
        _runner = None
    await _start_spectator_battle()


# ================================================================
# REST endpoints
# ================================================================


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/characters")
async def list_characters():
    """Return lightweight character summaries for the landing page."""
    from config_loader import load_character_summaries

    return load_character_summaries()


@app.delete("/api/characters/{character_id}")
async def delete_character(character_id: str):
    """Delete a character YAML file by id."""
    from config_loader import delete_character as _delete

    if _delete(character_id):
        return {"ok": True}
    from fastapi import HTTPException

    raise HTTPException(status_code=404, detail="Character not found")


@app.get("/api/models")
async def list_models():
    """Return available model adapters and current routing config."""
    from config_loader import load_llm_config

    llm_cfg = load_llm_config()
    adapters = []
    for provider_key, provider_cfg in llm_cfg.get("adapters", {}).items():
        for model_alias in provider_cfg.get("models", {}):
            adapters.append(f"{provider_key}/{model_alias}")

    routing = llm_cfg.get("routing", {})
    return {
        "adapters": adapters,
        "default": llm_cfg.get("default_adapter", ""),
        "routing": routing,
    }


@app.get("/api/sprites")
async def list_sprites():
    """Return available sprite presets (scanned from spritesheets directory)."""
    sprites_dir = STATIC_DIR / "assets" / "spritesheets"
    presets = []
    if sprites_dir.is_dir():
        for p in sorted(sprites_dir.glob("*.png")):
            preset_id = p.stem  # e.g. "Mecha_Samus"
            label = preset_id.replace("_", " ")
            presets.append({"id": preset_id, "label": label, "file": p.name})
    return presets


class GenerateCharacterRequest(BaseModel):
    name: str
    description: str
    sprite: str = ""
    save: bool = False


@app.post("/api/characters/generate")
async def generate_character_endpoint(req: GenerateCharacterRequest):
    """Generate a new character via LLM."""
    from character_generator import generate_character, save_character
    from config_loader import load_llm_config
    from runner import create_adapter

    llm_cfg = load_llm_config()
    adapter, _ = create_adapter(llm_cfg)

    sprite = req.sprite or None
    data = await asyncio.to_thread(
        lambda: generate_character(req.name, req.description, adapter, sprite=sprite)
    )

    if req.save:
        path = await asyncio.to_thread(save_character, data)
        data["saved_path"] = str(path)

    return {
        "id": data["name"].lower().replace(" ", "_"),
        "name": data["name"],
        "combat_class": data.get("combat_class", "warrior"),
        "backstory": data.get("backstory", ""),
        "personality_traits": data.get("personality_traits", []),
        "sprite": data.get("sprite", ""),
        "full": data,
    }


# ================================================================
# Campaign REST endpoints
# ================================================================


def _get_campaign_db():
    from campaign.persistence import CampaignDB

    return CampaignDB()


@app.get("/api/campaigns")
async def list_campaigns():
    """List all campaigns."""
    db = _get_campaign_db()
    try:
        campaigns = db.list_campaigns()
        return [
            {
                "id": c.campaign_id,
                "name": c.name,
                "created_at": c.created_at,
                "battle_count": c.battle_count,
            }
            for c in campaigns
        ]
    finally:
        db.close()


class CreateCampaignRequest(BaseModel):
    name: str
    character_ids: list[str] = []


@app.post("/api/campaigns")
async def create_campaign(req: CreateCampaignRequest):
    """Create a new campaign and seed its roster from selected characters."""
    from config_loader import load_all_characters

    db = _get_campaign_db()
    try:
        meta = db.create_campaign(req.name)

        # Load full agents and filter to selected IDs
        all_agents = load_all_characters()
        if req.character_ids:
            agents = [a for a in all_agents if a.agent_id in set(req.character_ids)]
        else:
            agents = all_agents

        from campaign.manager import roster_entry_from_agent

        roster = [roster_entry_from_agent(a) for a in agents]
        db.save_roster(meta.campaign_id, roster)

        return {
            "id": meta.campaign_id,
            "name": meta.name,
            "roster_size": len(roster),
        }
    finally:
        db.close()


@app.get("/api/campaigns/{campaign_id}")
async def get_campaign(campaign_id: int):
    """Get campaign details including roster and battle history."""
    from agent.moral_alignment import MoralAlignment

    db = _get_campaign_db()
    try:
        meta = db.get_campaign(campaign_id)
        if not meta:
            from fastapi.responses import JSONResponse

            return JSONResponse({"error": "Campaign not found"}, status_code=404)

        roster = db.load_roster(campaign_id)
        battles = db.load_battles(campaign_id)

        return {
            "id": meta.campaign_id,
            "name": meta.name,
            "created_at": meta.created_at,
            "battle_count": meta.battle_count,
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
                    "attack_range": r.attack_range,
                    "abilities": r.abilities,
                    "morality": r.morality,
                    "order_value": r.order_value,
                    "alignment_label": MoralAlignment(
                        morality=r.morality, order=r.order_value
                    ).label,
                }
                for r in roster
            ],
            "battles": [
                {
                    "battle_num": b.battle_num,
                    "winner_ids": b.winner_ids,
                    "death_ids": b.death_ids,
                    "rounds": b.rounds,
                    "xp_awards": b.xp_awards,
                    "timestamp": b.timestamp,
                }
                for b in battles
            ],
        }
    finally:
        db.close()


@app.delete("/api/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int):
    """Delete a campaign and all its data."""
    db = _get_campaign_db()
    try:
        db.delete_campaign(campaign_id)
        return {"deleted": True}
    finally:
        db.close()


# ================================================================
# WebSocket
# ================================================================


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        runner = await _get_or_create_runner()
        # Send full state restore if simulation is running
        restore = runner.get_restore()
        if restore:
            await ws.send_text(json.dumps(restore))

        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            cmd = msg.get("type", "")
            if cmd == "configure":
                if not SPECTATOR_MODE:
                    # Re-fetch runner — creates a fresh one if the previous battle finished
                    runner = await _get_or_create_runner()
                    runner.apply_configure(msg)
            elif cmd == "start":
                if not SPECTATOR_MODE:
                    await runner.start()
            elif cmd == "player_action":
                await runner.control_queue.put(msg)
            elif cmd in ("step", "play", "pause", "speed"):
                if cmd == "speed":
                    msg["delay"] = msg.get("delay", 500) / 1000.0
                await runner.control_queue.put(msg)

    except WebSocketDisconnect:
        manager.disconnect(ws)


def _find_available_port(start_port: int, host: str = "0.0.0.0", max_tries: int = 10) -> int:
    """Find the first available port starting at start_port."""
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(
        f"No available port found in range {start_port}-{start_port + max_tries - 1}"
    )


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="Battle-Agents frontend server")
    parser.add_argument(
        "--random",
        action="store_true",
        help="Use random actions instead of LLM",
    )
    parser.add_argument(
        "--no-social",
        action="store_true",
        help="Skip the pre-battle social phase",
    )
    parser.add_argument(
        "--chars",
        type=int,
        default=None,
        help="Number of characters to use",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to serve on (default: 8000)",
    )
    args = parser.parse_args()

    global _sim_options
    _sim_options = {
        "use_random": args.random,
        "no_social": args.random or args.no_social,
        "max_chars": args.chars,
    }

    mode = "random" if args.random else ("no-social" if args.no_social else "full")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log.info(f"Battle-Agents frontend — mode: {mode}")

    port = _find_available_port(args.port, host="0.0.0.0")
    if port != args.port:
        log.warning(f"Port {args.port} is in use — falling back to {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
