"""HTTP server for remote commands (phone-as-remote / iOS Shortcuts).

Single endpoint:

    POST /command
    Authorization: Bearer <token>
    Content-Type: application/json

    {"text": "what's on my calendar"}

Response (always JSON):

    {"skill": "calendar", "task": "Show today's calendar", "result": "..."}

Design notes
  - stdlib only (no FastAPI / aiohttp). Synchronous threading is fine —
    one user, low concurrency. Long Claude Code spawns block one thread.
  - Localhost-only by default. Set `server.host = "0.0.0.0"` to expose on
    LAN (Tailscale recommended for phone reach).
  - A bearer token is required. Set via `JARVIS_SERVER_TOKEN` env or
    `server.token` in config.
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Config
from .dispatcher import Dispatcher
from .memory import Memory
from .projects import resolve_project
from .router import route

log = logging.getLogger(__name__)


def serve(config: Config) -> int:
    if not config.server_token:
        log.error(
            "Refusing to start without a token. Set JARVIS_SERVER_TOKEN or "
            "server.token in ~/.jarvis/config.toml."
        )
        return 2

    # Build the same agent graph the daemon uses — minus audio.
    from .loop import _build_dispatcher  # local import to avoid circular at top

    memory = Memory()
    dispatcher, coder_shim = _build_dispatcher(config, memory)

    class Handler(BaseHTTPRequestHandler):
        # Quiet down the default access log; we have our own.
        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            log.debug("HTTP " + fmt, *args)

        def _json(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/command":
                self._json(404, {"error": "not found"})
                return
            auth = self.headers.get("Authorization", "")
            if auth != f"Bearer {config.server_token}":
                self._json(401, {"error": "unauthorized"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            try:
                body = self.rfile.read(length).decode("utf-8")
                payload = json.loads(body) if body else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json(400, {"error": "invalid JSON body"})
                return

            text = (payload.get("text") or "").strip()
            if not text:
                self._json(400, {"error": "missing 'text'"})
                return

            proj, cleaned = resolve_project(text, config.projects)
            if proj is not None:
                coder_shim.set_next_project(proj.name)

            decision = route(cleaned, memory=memory)
            result = dispatcher.execute(decision)
            memory.append(text, decision.skill, result)
            self._json(
                200,
                {"skill": decision.skill, "task": decision.task, "result": result},
            )

        # Health check — no auth, useful for monitoring.
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/healthz":
                self._json(200, {"ok": True})
                return
            self._json(404, {"error": "not found"})

    addr = (config.server_host, config.server_port)
    httpd = ThreadingHTTPServer(addr, Handler)
    log.info("Jarvis HTTP server listening on http://%s:%d", *addr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down server.")
    finally:
        httpd.server_close()
    return 0
