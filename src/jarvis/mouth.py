"""Text-to-speech with platform-appropriate fallbacks.

Priority order:
  1. ElevenLabs streaming (highest quality, cloud — if key configured)
  2. macOS `say`           (Mac, built-in)
  3. Windows SAPI          (Windows, built-in via PowerShell)
  4. print(...)            (last resort — never silent)

No extra package needed on either OS — SAPI ships with Windows, `say` ships
with macOS. Add ElevenLabs at any time for the quality upgrade.
"""
from __future__ import annotations

import logging
import platform
import shutil
import subprocess

log = logging.getLogger(__name__)


def _windows_sapi_available() -> bool:
    if platform.system() != "Windows":
        return False
    return shutil.which("powershell.exe") is not None or shutil.which("pwsh.exe") is not None


def _speak_windows_sapi(text: str) -> bool:
    """TTS via PowerShell's System.Speech.Synthesis. Returns True on success."""
    powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if powershell is None:
        return False
    # Escape single quotes for PowerShell single-quoted string literal.
    escaped = text.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Speech;"
        f"(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{escaped}')"
    )
    try:
        subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=30,
            check=False,
        )
        return True
    except Exception:
        log.exception("Windows SAPI TTS failed")
        return False


class Mouth:
    def __init__(
        self,
        elevenlabs_key: str | None = None,
        voice_id: str = "EXAVITQu4vr4xnSDxMaL",
        model: str = "eleven_turbo_v2_5",
    ):
        self.voice_id = voice_id
        self.model = model
        self._client = None
        self._have_say = shutil.which("say") is not None
        self._have_sapi = _windows_sapi_available()

        if elevenlabs_key:
            try:
                from elevenlabs.client import ElevenLabs
                self._client = ElevenLabs(api_key=elevenlabs_key)
                log.info("ElevenLabs TTS ready (voice=%s)", voice_id)
            except ImportError:
                log.warning("elevenlabs package not installed; falling back")

        if self._client is None:
            if self._have_say:
                log.info("Using macOS `say` for TTS")
            elif self._have_sapi:
                log.info("Using Windows SAPI for TTS")
            else:
                log.warning("No TTS backend available; will print to stdout")

    def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        log.info("Saying: %s", text[:80])
        if self._client is not None:
            try:
                self._speak_elevenlabs(text)
                return
            except Exception:
                log.exception("ElevenLabs failed; trying platform fallback")
        if self._have_say:
            subprocess.run(["say", text], check=False)
            return
        if self._have_sapi and _speak_windows_sapi(text):
            return
        print(f"[TTS] {text}")

    def _speak_elevenlabs(self, text: str) -> None:
        from elevenlabs import stream
        audio_stream = self._client.text_to_speech.convert_as_stream(
            text=text,
            voice_id=self.voice_id,
            model_id=self.model,
        )
        stream(audio_stream)
