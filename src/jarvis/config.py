"""Load config from ~/.jarvis/config.toml with env overrides."""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    picovoice_key: str
    elevenlabs_key: str | None
    elevenlabs_voice_id: str
    elevenlabs_model: str
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    default_project: Path
    claude_bin: str
    dangerously_skip_permissions: bool
    timeout_seconds: int
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
            raise ValueError(
                "Picovoice access key missing. Set PICOVOICE_KEY env or fill picovoice.access_key in config."
            )

        elevenlabs_key = os.getenv("ELEVENLABS_KEY") or eleven.get("api_key")
        if elevenlabs_key and elevenlabs_key.startswith("YOUR_"):
            elevenlabs_key = None

        return cls(
            picovoice_key=picovoice_key,
            elevenlabs_key=elevenlabs_key,
            elevenlabs_voice_id=eleven.get("voice_id", "EXAVITQu4vr4xnSDxMaL"),
            elevenlabs_model=eleven.get("model", "eleven_turbo_v2_5"),
            whisper_model=whisper.get("model", "base.en"),
            whisper_device=whisper.get("device", "cpu"),
            whisper_compute_type=whisper.get("compute_type", "int8"),
            default_project=Path(coder.get("default_project", "~")).expanduser(),
            claude_bin=coder.get("claude_bin", "claude"),
            dangerously_skip_permissions=bool(coder.get("dangerously_skip_permissions", False)),
            timeout_seconds=int(coder.get("timeout_seconds", 600)),
            vad_aggressiveness=int(vad.get("aggressiveness", 2)),
            silence_seconds=float(vad.get("silence_seconds", 1.0)),
            max_utterance_seconds=float(vad.get("max_utterance_seconds", 30.0)),
            log_level=data.get("log_level", "INFO"),
        )


if sys.version_info < (3, 11):
    raise RuntimeError("Jarvis requires Python 3.11+ (uses tomllib).")
