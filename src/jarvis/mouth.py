"""Text-to-speech.

Default: ElevenLabs streaming (low latency, high quality).
Fallback: macOS `say` (free, works offline, OK quality).
"""
from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger(__name__)


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
                log.exception("ElevenLabs failed; falling back to `say`")
        if self._have_say:
            subprocess.run(["say", text], check=False)
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
