"""HTTP server tests. Spins the real ThreadingHTTPServer on an ephemeral port."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis.config import Config
from jarvis.projects import Project
from jarvis.router import Routed


def _make_config(tmp_path: Path, token: str | None = "test-token") -> Config:
    return Config(
        picovoice_key=None,
        wake_word_backend="none",
        openwakeword_threshold=0.5,
        elevenlabs_key=None,
        elevenlabs_voice_id="x",
        elevenlabs_model="x",
        whisper_model="x",
        whisper_device="cpu",
        whisper_compute_type="int8",
        default_project=tmp_path,
        projects=(Project(name="test", path=tmp_path),),
        claude_bin="claude",
        dangerously_skip_permissions=False,
        timeout_seconds=10,
        mcp_config_path=tmp_path / "mcp.json",
        mail_backend="applescript",
        calendar_backend="google",
        google_credentials_path=tmp_path / "creds.json",
        google_token_path=tmp_path / "token.json",
        contacts_path=tmp_path / "contacts.toml",
        watcher_vip_senders=(),
        watcher_calendar_lead_minutes=0,
        watcher_trello_list="",
        skills_dir=tmp_path / "skills",
        server_host="127.0.0.1",
        server_port=0,  # will be patched per test
        server_token=token,
        orb_port=0,
        vad_aggressiveness=2,
        silence_seconds=1.0,
        max_utterance_seconds=30.0,
        engaged_timeout_seconds=90.0,
        log_level="WARNING",
    )


def test_server_refuses_without_token(tmp_path: Path):
    from jarvis.server import serve

    code = serve(_make_config(tmp_path, token=None))
    assert code == 2


def _free_port() -> int:
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def running_server(tmp_path: Path):
    port = _free_port()
    config = _make_config(tmp_path)
    object.__setattr__(config, "server_port", port)

    # Avoid touching real Coder.check() at startup — it requires `claude` on PATH.
    with patch("jarvis.loop._build_dispatcher") as build, patch(
        "jarvis.router.route", return_value=Routed(skill="direct", task="hi")
    ):
        class FakeDispatcher:
            def execute(self, decision):
                return f"ok:{decision.skill}:{decision.task}"

        class FakeShim:
            def set_next_project(self, _): pass

        build.return_value = (FakeDispatcher(), FakeShim())

        # serve() blocks — run in a thread
        from jarvis.server import serve

        t = threading.Thread(target=serve, args=(config,), daemon=True)
        t.start()
        # Wait for the port to bind
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.2).read()
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.05)
        yield port, "test-token"


def _post(port: int, token: str | None, body: dict) -> tuple[int, dict | None]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/command",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}
        | ({"Authorization": f"Bearer {token}"} if token else {}),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.getcode(), json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, None


def test_healthz_is_open(running_server):
    port, _ = running_server
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as r:
        assert r.getcode() == 200


def test_command_requires_auth(running_server):
    port, _ = running_server
    code, _ = _post(port, token=None, body={"text": "hi"})
    assert code == 401


def test_command_rejects_wrong_token(running_server):
    port, _ = running_server
    code, _ = _post(port, token="wrong", body={"text": "hi"})
    assert code == 401


def test_command_requires_text(running_server):
    port, token = running_server
    code, _ = _post(port, token=token, body={})
    assert code == 400


def test_command_returns_dispatch_result(running_server):
    port, token = running_server
    code, payload = _post(port, token=token, body={"text": "hello"})
    assert code == 200
    assert payload["skill"] == "direct"
    assert payload["result"].startswith("ok:")
