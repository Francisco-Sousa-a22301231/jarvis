"""Tiny localhost-only HTTP server that serves the orb UI.

The daemon starts this in a background thread on startup. Two endpoints:
  GET /        → the orb HTML page (self-contained, no external assets)
  GET /state   → current JarvisState as JSON (polled by the HTML)

Localhost-only by design — no auth, no remote access. For phone-as-remote
use the separate `jarvis serve` HTTP server which has bearer auth.
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import StateTracker

log = logging.getLogger(__name__)

DEFAULT_PORT = 8780


_ORB_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Jarvis</title>
<style>
  :root { color-scheme: dark; }
  html, body {
    margin: 0; padding: 0;
    background: #08080d;
    color: #f3f4f6;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    height: 100vh; width: 100vw; overflow: hidden;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    user-select: none;
  }
  .orb {
    width: 320px; height: 320px; border-radius: 50%;
    background: radial-gradient(circle at 30% 30%, #2a3a5a 0%, #0a1530 60%, #050811 100%);
    box-shadow: 0 0 80px 10px rgba(80,120,200,0.25), inset 0 0 60px rgba(255,255,255,0.05);
    transition: background 0.4s ease, box-shadow 0.4s ease;
    animation: breathe 5s infinite ease-in-out;
  }
  .label {
    margin-top: 36px; font-size: 14px; opacity: 0.65;
    text-transform: uppercase; letter-spacing: 6px; font-weight: 500;
    transition: color 0.4s ease;
  }
  .text {
    margin-top: 14px; font-size: 14px; opacity: 0.55;
    max-width: 80%; text-align: center; min-height: 1.2em;
    font-style: italic;
  }
  .footer {
    position: absolute; bottom: 14px; font-size: 11px; opacity: 0.3;
    letter-spacing: 2px; text-transform: uppercase;
  }

  /* State-specific styling */
  .orb.idle    { animation: breathe 5s infinite ease-in-out; }
  .orb.engaged {
    background: radial-gradient(circle at 30% 30%, #a78bfa 0%, #4c1d95 60%, #1a0a35 100%);
    box-shadow: 0 0 110px 20px rgba(167,139,250,0.45), inset 0 0 60px rgba(255,255,255,0.08);
    animation: breathe 2.5s infinite ease-in-out;
  }
  .orb.booting {
    background: radial-gradient(circle at 30% 30%, #4b5563 0%, #1f2937 60%, #050811 100%);
    box-shadow: 0 0 80px 10px rgba(156,163,175,0.25);
    animation: spin 3s infinite linear;
  }
  .orb.listening {
    background: radial-gradient(circle at 30% 30%, #4ade80 0%, #166534 60%, #052e16 100%);
    box-shadow: 0 0 120px 30px rgba(74,222,128,0.55), inset 0 0 60px rgba(255,255,255,0.08);
    animation: pulse 1.2s infinite ease-in-out;
  }
  .orb.thinking {
    background: radial-gradient(circle at 30% 30%, #facc15 0%, #854d0e 60%, #1a1206 100%);
    box-shadow: 0 0 120px 30px rgba(250,204,21,0.55);
    animation: spin 2s infinite linear;
  }
  .orb.speaking {
    background: radial-gradient(circle at 30% 30%, #38bdf8 0%, #0c4a6e 60%, #051e30 100%);
    box-shadow: 0 0 120px 35px rgba(56,189,248,0.6), inset 0 0 60px rgba(255,255,255,0.1);
    animation: pulse 0.55s infinite ease-in-out;
  }
  .orb.offline {
    background: radial-gradient(circle at 30% 30%, #374151 0%, #111827 60%, #050811 100%);
    box-shadow: 0 0 40px 5px rgba(55,65,81,0.2);
    animation: none;
    opacity: 0.5;
  }

  @keyframes breathe { 0%,100% { transform: scale(1.0); } 50% { transform: scale(1.04); } }
  @keyframes pulse   { 0%,100% { transform: scale(1.0); } 50% { transform: scale(1.10); } }
  @keyframes spin    { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
</style>
</head>
<body>
  <div id="orb" class="orb offline"></div>
  <div id="label" class="label">offline</div>
  <div id="text" class="text"></div>
  <div class="footer">jarvis</div>
<script>
  const orb = document.getElementById('orb');
  const label = document.getElementById('label');
  const text = document.getElementById('text');
  let lastState = '';
  async function poll() {
    try {
      const r = await fetch('/state', { cache: 'no-store' });
      if (!r.ok) return;
      const s = await r.json();
      if (s.state !== lastState) {
        orb.className = 'orb ' + s.state;
        label.textContent = s.state;
        lastState = s.state;
      }
      text.textContent = s.text || '';
    } catch (_) { /* network glitch, retry next tick */ }
  }
  setInterval(poll, 150);
  poll();
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    tracker: "StateTracker | None" = None  # set on the class before serving

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        log.debug("orb HTTP " + fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/orb"):
            body = _ORB_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/state":
            payload = self.tracker.snapshot() if self.tracker else {"state": "offline"}
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


def start(tracker: "StateTracker", port: int = DEFAULT_PORT) -> tuple[ThreadingHTTPServer, int]:
    """Start the orb HTTP server in a daemon thread. Returns (httpd, port).

    If the requested port is taken (likely a previous daemon still bound),
    we try the next 5 ports up.
    """
    _Handler.tracker = tracker
    last_err: Exception | None = None
    for p in range(port, port + 6):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), _Handler)
            break
        except OSError as e:
            last_err = e
            continue
    else:
        raise RuntimeError(f"No free port in {port}-{port + 5}: {last_err}")

    threading.Thread(target=httpd.serve_forever, daemon=True, name="orb-server").start()
    log.info("Orb UI: http://127.0.0.1:%d/", p)
    return httpd, p
