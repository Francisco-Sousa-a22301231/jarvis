"""Load config from ~/.jarvis/config.toml with env overrides."""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .projects import Project


@dataclass(frozen=True)
class Config:
    # picovoice_key is None when not configured. Only the daemon subcommand
    # needs it; `brief`, `route`, and `qa` work fine without audio.
    picovoice_key: str | None
    elevenlabs_key: str | None
    elevenlabs_voice_id: str
    elevenlabs_model: str
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    default_project: Path
    projects: tuple[Project, ...]
    claude_bin: str
    dangerously_skip_permissions: bool
    timeout_seconds: int
    mcp_config_path: Path
    mail_backend: str  # "applescript" (default, macOS Mail) or "gmail" (OAuth)
    gmail_credentials_path: Path
    gmail_token_path: Path
    contacts_path: Path
    watcher_vip_senders: tuple[str, ...]
    vad_aggressiveness: int
    silence_seconds: float
    max_utterance_seconds: float
    log_level: str

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or Path.home() / ".jarvis" / "config.toml"
        if not path.exists():
            raise FileNotFoundError(
                f"Config not found at {path}.\n"
                f"Run: mkdir -p ~/.jarvis && cp config.example.toml ~/.jarvis/config.toml"
            )
        with path.open("rb") as f:
            data = tomllib.load(f)

        eleven = data.get("elevenlabs", {})
        coder = data.get("coder", {})
        whisper = data.get("whisper", {})
        vad = data.get("vad", {})
        pico = data.get("picovoice", {})

        picovoice_key = os.getenv("PICOVOICE_KEY") or pico.get("access_key", "")
        if not picovoice_key or picovoice_key.startswith("YOUR_"):
            picovoice_key = None  # daemon will validate at startup

        elevenlabs_key = os.getenv("ELEVENLABS_KEY") or eleven.get("api_key")
        if elevenlabs_key and elevenlabs_key.startswith("YOUR_"):
            elevenlabs_key = None

        # Build projects tuple. Prefer the explicit [[projects]] array;
        # fall back to a single-project list from coder.default_project so
        # existing configs keep working untouched.
        raw_projects = data.get("projects", [])
        if raw_projects:
            projects = tuple(
                Project(
                    name=str(p["name"]),
                    path=Path(p["path"]).expanduser(),
                    aliases=tuple(p.get("aliases", [])),
                )
                for p in raw_projects
            )
        else:
            single = Path(coder.get("default_project", "~")).expanduser()
            projects = (Project(name=single.name, path=single),)
        default_project = projects[0].path

        return cls(
            picovoice_key=picovoice_key,
            elevenlabs_key=elevenlabs_key,
            elevenlabs_voice_id=eleven.get("voice_id", "EXAVITQu4vr4xnSDxMaL"),
            elevenlabs_model=eleven.get("model", "eleven_turbo_v2_5"),
            whisper_model=whisper.get("model", "base.en"),
            whisper_device=whisper.get("device", "cpu"),
            whisper_compute_type=whisper.get("compute_type", "int8"),
            default_project=default_project,
            projects=projects,
            claude_bin=coder.get("claude_bin", "claude"),
            dangerously_skip_permissions=bool(coder.get("dangerously_skip_permissions", False)),
            timeout_seconds=int(coder.get("timeout_seconds", 600)),
            mcp_config_path=Path(
                data.get("qa", {}).get("mcp_config", "~/.jarvis/mcp.json")
            ).expanduser(),
            mail_backend=data.get("mail", {}).get("backend", "applescript"),
            gmail_credentials_path=Path(
                data.get("mail", {}).get(
                    "gmail_credentials", "~/.jarvis/gmail-credentials.json"
                )
            ).expanduser(),
            gmail_token_path=Path(
                data.get("mail", {}).get("gmail_token", "~/.jarvis/gmail-token.json")
            ).expanduser(),
            contacts_path=Path(
                data.get("mail", {}).get("contacts", "~/.jarvis/contacts.toml")
            ).expanduser(),
            watcher_vip_senders=tuple(
                data.get("watcher", {}).get("vip_senders", [])
            ),
            vad_aggressiveness=int(vad.get("aggressiveness", 2)),
            silence_seconds=float(vad.get("silence_seconds", 1.0)),
            max_utterance_seconds=float(vad.get("max_utterance_seconds", 30.0)),
            log_level=data.get("log_level", "INFO"),
        )


if sys.version_info < (3, 11):
    raise RuntimeError("Jarvis requires Python 3.11+ (uses tomllib).")
