"""Load config from ~/.jarvis/config.toml with env overrides."""
from __future__ import annotations

import os
import platform
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .projects import Project


def _default_mail_backend() -> str:
    """applescript on macOS (zero setup), gmail elsewhere."""
    return "applescript" if platform.system() == "Darwin" else "gmail"


@dataclass(frozen=True)
class Config:
    # picovoice_key is None when not configured. Only the daemon subcommand
    # needs it; `brief`, `route`, and `qa` work fine without audio.
    picovoice_key: str | None
    wake_word_backend: str  # "openwakeword" (default) | "porcupine" | "none"
    openwakeword_threshold: float
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
    mail_backend: str  # "applescript" (macOS Mail) or "gmail" (cross-platform)
    calendar_backend: str  # "google" (default, cross-platform) or "applescript"
    google_credentials_path: Path
    google_token_path: Path
    contacts_path: Path
    watcher_vip_senders: tuple[str, ...]
    watcher_calendar_lead_minutes: int
    watcher_trello_list: str
    skills_dir: Path
    server_host: str
    server_port: int
    server_token: str | None
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

        ww = data.get("wake_word", {})
        # If user explicitly sets a backend, use it. Otherwise pick a sensible
        # default: porcupine if they have a key, openwakeword otherwise.
        wake_word_backend = ww.get("backend")
        if not wake_word_backend:
            wake_word_backend = "porcupine" if picovoice_key else "openwakeword"

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
            wake_word_backend=wake_word_backend,
            openwakeword_threshold=float(ww.get("openwakeword_threshold", 0.6)),
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
            mail_backend=data.get("mail", {}).get("backend", _default_mail_backend()),
            calendar_backend=data.get("calendar", {}).get("backend", "google"),
            google_credentials_path=Path(
                # Prefer [google].credentials; fall back to legacy
                # [mail].gmail_credentials for existing configs.
                data.get("google", {}).get("credentials")
                or data.get("mail", {}).get(
                    "gmail_credentials", "~/.jarvis/google-credentials.json"
                )
            ).expanduser(),
            google_token_path=Path(
                data.get("google", {}).get("token")
                or data.get("mail", {}).get("gmail_token", "~/.jarvis/google-token.json")
            ).expanduser(),
            contacts_path=Path(
                data.get("mail", {}).get("contacts", "~/.jarvis/contacts.toml")
            ).expanduser(),
            watcher_vip_senders=tuple(
                data.get("watcher", {}).get("vip_senders", [])
            ),
            watcher_calendar_lead_minutes=int(
                data.get("watcher", {}).get("calendar_lead_minutes", 0)
            ),
            watcher_trello_list=str(
                data.get("watcher", {}).get("trello_list", "")
            ),
            skills_dir=Path(
                data.get("skills", {}).get("dir", "~/.jarvis/skills")
            ).expanduser(),
            server_host=str(data.get("server", {}).get("host", "127.0.0.1")),
            server_port=int(data.get("server", {}).get("port", 8765)),
            server_token=(
                os.getenv("JARVIS_SERVER_TOKEN")
                or data.get("server", {}).get("token")
            ),
            vad_aggressiveness=int(vad.get("aggressiveness", 2)),
            silence_seconds=float(vad.get("silence_seconds", 1.0)),
            max_utterance_seconds=float(vad.get("max_utterance_seconds", 30.0)),
            log_level=data.get("log_level", "INFO"),
        )


if sys.version_info < (3, 11):
    raise RuntimeError("Jarvis requires Python 3.11+ (uses tomllib).")
