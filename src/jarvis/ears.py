"""Wake word + voice capture + STT.

Pipeline: <wake backend> -> webrtcvad (endpointing) -> faster-whisper (STT).
All local. No audio leaves the machine on the input side.

Wake-word backend is pluggable:
  - "openwakeword": open-source, no API key, default. Uses the bundled
    hey_jarvis model from dscripka/openWakeWord (Apache 2.0 code,
    CC-BY-NC-SA models — fine for personal use).
  - "porcupine": Picovoice's commercial wake word. Better detection
    quality but requires an access key (and Picovoice can gate signup).

Push-to-talk via `jarvis listen` skips the wake-word entirely.
"""
from __future__ import annotations

import logging
import struct
from typing import Protocol

import numpy as np
import pvporcupine
import sounddevice as sd
import webrtcvad
from faster_whisper import WhisperModel

log = logging.getLogger(__name__)


class WakeBackend(Protocol):
    frame_length: int

    def process(self, pcm_int16) -> bool:
        """True iff the wake word was detected in this frame."""

    def reset(self) -> None:
        """Clear any buffered audio so a new wake cycle starts clean."""

    def close(self) -> None: ...


class PorcupineBackend:
    def __init__(self, access_key: str):
        self._p = pvporcupine.create(access_key=access_key, keywords=["jarvis"])
        self.frame_length = self._p.frame_length  # 512 samples @ 16kHz

    def process(self, pcm_int16) -> bool:
        return self._p.process(pcm_int16) >= 0

    def reset(self) -> None:
        pass  # Porcupine has no persistent buffer to clear

    def close(self) -> None:
        self._p.delete()


class OpenWakeWordBackend:
    """Default — no API key required.

    The hey_jarvis_v0.1 ONNX model (~1.3 MB) is auto-downloaded on first
    use to the openwakeword package cache. Subsequent runs are silent.
    """

    DEFAULT_MODEL = "hey_jarvis_v0.1"

    def __init__(self, threshold: float = 0.5, model_name: str | None = None):
        from openwakeword.model import Model
        from openwakeword.utils import download_models

        self.threshold = threshold
        self.model_name = model_name or self.DEFAULT_MODEL
        # Ensure the model files exist locally.
        download_models([self.model_name.split("_v")[0]])
        # 1280 samples (80ms @ 16kHz) is the standard frame size for openWakeWord.
        self.frame_length = 1280
        self._m = Model(
            wakeword_models=[self.model_name],
            inference_framework="onnx",
        )
        log.info("openWakeWord loaded (%s, threshold=%.2f)", self.model_name, threshold)

    def process(self, pcm_int16) -> bool:
        audio = np.asarray(pcm_int16, dtype=np.int16)
        pred = self._m.predict(audio)
        score = pred.get(self.model_name, 0.0)
        if score >= self.threshold:
            log.debug("wake score=%.3f", score)
            return True
        return False

    def reset(self) -> None:
        """Clear the model's internal audio history.

        Without this, after a wake-word detection (or after TTS playback that
        the mic re-heard), the model's buffer still contains audio matching
        the wake word and immediately triggers again on the next process()
        call — the classic feedback loop.
        """
        try:
            self._m.reset()
        except Exception:
            log.exception("openWakeWord reset failed (non-fatal)")

    def close(self) -> None:
        pass  # nothing to free


def build_wake_backend(
    *,
    backend: str,
    picovoice_key: str | None,
    openwakeword_threshold: float,
) -> WakeBackend | None:
    """Return the configured wake-word backend, or None for push-to-talk mode."""
    if backend == "none":
        return None
    if backend == "porcupine":
        if not picovoice_key:
            raise RuntimeError(
                "wake_word.backend = 'porcupine' but no picovoice access key. "
                "Set [picovoice].access_key or switch to 'openwakeword'."
            )
        return PorcupineBackend(picovoice_key)
    if backend == "openwakeword":
        return OpenWakeWordBackend(threshold=openwakeword_threshold)
    raise RuntimeError(
        f"Unknown wake_word.backend={backend!r}. "
        "Choose 'openwakeword' (default), 'porcupine', or 'none'."
    )


class Ears:
    SAMPLE_RATE = 16000
    VAD_FRAME_MS = 30  # webrtcvad accepts 10, 20, or 30

    def __init__(
        self,
        wake_backend: WakeBackend | None = None,
        whisper_model: str = "base.en",
        whisper_device: str = "cpu",
        whisper_compute_type: str = "int8",
        vad_aggressiveness: int = 2,
    ):
        self.wake = wake_backend
        self.vad = webrtcvad.Vad(vad_aggressiveness)
        log.info(
            "Loading Whisper model %s (%s, %s)...",
            whisper_model, whisper_device, whisper_compute_type,
        )
        self.whisper = WhisperModel(
            whisper_model,
            device=whisper_device,
            compute_type=whisper_compute_type,
        )
        log.info("Whisper ready.")

    def wait_for_wake(self) -> None:
        """Block until wake word detected."""
        if self.wake is None:
            raise RuntimeError(
                "No wake backend configured. Use `jarvis listen` for push-to-talk."
            )
        frame_len = self.wake.frame_length
        with sd.RawInputStream(
            samplerate=self.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=frame_len,
        ) as stream:
            while True:
                data, overflow = stream.read(frame_len)
                if overflow:
                    log.debug("Audio overflow during wake listen")
                pcm = struct.unpack_from("h" * frame_len, bytes(data))
                if self.wake.process(pcm):
                    log.info("Wake word detected")
                    # Clear the model's buffer so the same wake event
                    # doesn't re-trigger on the next call.
                    self.wake.reset()
                    return

    def record_utterance(
        self,
        max_seconds: float = 30.0,
        silence_seconds: float = 1.0,
    ) -> np.ndarray:
        """Record audio until silence_seconds of trailing silence or max_seconds."""
        frame_samples = int(self.SAMPLE_RATE * self.VAD_FRAME_MS / 1000)
        silence_target = int(silence_seconds * 1000 / self.VAD_FRAME_MS)
        max_frames = int(max_seconds * 1000 / self.VAD_FRAME_MS)

        chunks: list[bytes] = []
        silence_count = 0
        spoke = False

        with sd.RawInputStream(
            samplerate=self.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=frame_samples,
        ) as stream:
            for _ in range(max_frames):
                data, _overflow = stream.read(frame_samples)
                frame = bytes(data)
                chunks.append(frame)
                try:
                    is_speech = self.vad.is_speech(frame, self.SAMPLE_RATE)
                except Exception:
                    is_speech = False

                if is_speech:
                    spoke = True
                    silence_count = 0
                else:
                    silence_count += 1
                    if spoke and silence_count >= silence_target:
                        break

        if not spoke:
            return np.zeros(0, dtype=np.float32)

        raw = b"".join(chunks)
        audio_i16 = np.frombuffer(raw, dtype=np.int16)
        return audio_i16.astype(np.float32) / 32768.0

    def transcribe(self, audio: np.ndarray) -> str:
        if audio.size == 0:
            return ""
        # Minimum length guard against Whisper hallucinations on tiny clips.
        if audio.size < self.SAMPLE_RATE * 0.3:
            return ""
        segments, _info = self.whisper.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=False,  # webrtcvad already handled endpointing
        )
        return " ".join(s.text for s in segments).strip()

    def close(self) -> None:
        if self.wake is not None:
            self.wake.close()
