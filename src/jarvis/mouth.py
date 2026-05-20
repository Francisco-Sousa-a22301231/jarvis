"""Text-to-speech with platform-appropriate fallbacks.

Priority order:
  1. edge-tts (Microsoft neural voices, free, sounds basically human)
  2. ElevenLabs (still highest quality if you have a key)
  3. macOS `say`
  4. Windows SAPI
  5. print(...)

edge-tts is the new recommended path on Windows — SAPI sounds robotic and
Windows only ships a basic en-US voice (Zira) without manual install.
edge-tts uses Microsoft Edge's free unofficial cloud TTS — Apache 2.0
PyPI package, no signup.
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import subprocess
import tempfile

log = logging.getLogger(__name__)

DEFAULT_EDGE_VOICE = "en-US-AriaNeural"


def _edge_tts_available() -> bool:
    try:
        import edge_tts  # noqa: F401
        import pygame  # noqa: F401
        return True
    except ImportError:
        return False


def _windows_sapi_available() -> bool:
    if platform.system() != "Windows":
        return False
    return shutil.which("powershell.exe") is not None or shutil.which("pwsh.exe") is not None


def _speak_edge_tts(text: str, voice: str) -> bool:
    """Synthesise via edge-tts to a temp MP3, then play with pygame. True on success."""
    try:
        import edge_tts
        import pygame.mixer
    except ImportError:
        return False

    async def _save(path: str) -> None:
        comm = edge_tts.Communicate(text, voice)
        await comm.save(path)

    f = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    f.close()
    try:
        asyncio.run(_save(f.name))
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        snd = pygame.mixer.Sound(f.name)
        ch = snd.play()
        while ch.get_busy():
            pygame.time.delay(40)
        return True
    except Exception:
        log.exception("edge-tts playback failed")
        return False
    finally:
        try:
            os.unlink(f.name)
        except OSError:
            pass


def _speak_windows_sapi(text: str) -> bool:
    """TTS via PowerShell's System.Speech.Synthesis. Returns True on success."""
    powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if powershell is None:
        return False
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
        edge_voice: str = DEFAULT_EDGE_VOICE,
    ):
        self.voice_id = voice_id
        self.model = model
        self.edge_voice = edge_voice
        self._client = None
        self._have_say = shutil.which("say") is not None
        self._have_sapi = _windows_sapi_available()
        self._have_edge = _edge_tts_available()

        if elevenlabs_key:
            try:
                from elevenlabs.client import ElevenLabs
                self._client = ElevenLabs(api_key=elevenlabs_key)
                log.info("ElevenLabs TTS ready (voice=%s)", voice_id)
            except ImportError:
                log.warning("elevenlabs package not installed; falling back")

        # Log the active backend so the daemon-startup output makes it
        # obvious which voice the user will hear.
        if self._client is not None:
            backend = "ElevenLabs"
        elif self._have_edge:
            backend = f"edge-tts ({edge_voice})"
        elif self._have_say:
            backend = "macOS say"
        elif self._have_sapi:
            backend = "Windows SAPI"
        else:
            backend = "print fallback"
        log.info("TTS backend: %s", backend)

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
                log.exception("ElevenLabs failed; trying next backend")
        if self._have_edge and _speak_edge_tts(text, self.edge_voice):
            return
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

    def prewarm(self) -> None:
        """Open the TTS connection eagerly so the first real `speak()` doesn't
        pay the cold-start cost. Currently only meaningful for edge-tts: we
        do a tiny throwaway synthesis to warm the HTTPS connection and let
        pygame.mixer initialise. ~1 second of work hidden during boot.
        """
        if self._client is not None:
            return  # ElevenLabs streaming has its own warmup
        if not self._have_edge:
            return
        try:
            import pygame.mixer
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            # Use a single-letter text and don't actually play it.
            import asyncio
            import os
            import tempfile
            import edge_tts

            async def _warm():
                f = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                f.close()
                try:
                    comm = edge_tts.Communicate("hi", self.edge_voice)
                    await comm.save(f.name)
                finally:
                    try:
                        os.unlink(f.name)
                    except OSError:
                        pass

            asyncio.run(_warm())
            log.info("TTS prewarmed")
        except Exception:
            log.exception("TTS prewarm failed (non-fatal)")
