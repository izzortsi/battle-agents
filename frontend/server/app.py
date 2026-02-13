"""FastAPI application — serves the frontend and manages WebSocket connections."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Battle-Agents")
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
    """Create the SimRunner on first use."""
    global _runner
    async with _runner_lock:
        if _runner is None:
            from frontend.server.sim_runner import SimRunner

            _runner = SimRunner(manager, **_sim_options)
        return _runner


@app.get("/")
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


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
            if cmd == "start":
                # Start is handled directly (not via queue) to avoid
                # chicken-and-egg: _run() reads the queue but _run()
                # must be started first.
                await runner.start()
            elif cmd in ("step", "play", "pause", "speed"):
                if cmd == "speed":
                    msg["delay"] = msg.get("delay", 500) / 1000.0
                await runner.control_queue.put(msg)

    except WebSocketDisconnect:
        manager.disconnect(ws)


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

    uvicorn.run(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
