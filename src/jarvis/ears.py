"""Wake word + voice capture + STT.

Pipeline: Porcupine (wake) -> webrtcvad (endpointing) -> faster-whisper (STT).
All local. No audio leaves the machine on the input side.
"""
from __future__ import annotations

import logging
import struct

import numpy as np
import pvporcupine
import sounddevice as sd
import webrtcvad
from faster_whisper import WhisperModel

log = logging.getLogger(__name__)


class Ears:
    SAMPLE_RATE = 16000
    VAD_FRAME_MS = 30  # webrtcvad accepts 10, 20, or 30

    def __init__(
        self,
        picovoice_key: str | None = None,
        whisper_model: str = "base.en",
        whisper_device: str = "cpu",
        whisper_compute_type: str = "int8",
        vad_aggressiveness: int = 2,
    ):
        # Porcupine is optional — push-to-talk mode (`jarvis listen`) and the
        # HTTP server work fine without a wake word. Only the always-on
        # daemon needs it.
        self.porcupine = None
        if picovoice_key:
            self.porcupine = pvporcupine.create(
                access_key=picovoice_key,
                keywords=["jarvis"],
            )
        self.vad = webrtcvad.Vad(vad_aggressiveness)
        log.info("Loading Whisper model %s (%s, %s)...", whisper_model, whisper_device, whisper_compute_type)
        self.whisper = WhisperModel(
            whisper_model,
            device=whisper_device,
            compute_type=whisper_compute_type,
        )
        log.info("Whisper ready.")

    @property
    def porcupine_frame_length(self) -> int:
        if self.porcupine is None:
            raise RuntimeError("Wake word disabled — call record_utterance() directly.")
        return self.porcupine.frame_length  # 512 samples @ 16kHz

    def wait_for_wake(self) -> None:
        """Block until 'Jarvis' wake word detected."""
        if self.porcupine is None:
            raise RuntimeError(
                "Wake word disabled (no Picovoice key configured). "
                "Use `jarvis listen` for push-to-talk instead."
            )
        with sd.RawInputStream(
            samplerate=self.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=self.porcupine_frame_length,
        ) as stream:
            while True:
                data, overflow = stream.read(self.porcupine_frame_length)
                if overflow:
                    log.debug("Audio overflow during wake listen")
                pcm = struct.unpack_from(
                    "h" * self.porcupine_frame_length, bytes(data)
                )
                if self.porcupine.process(pcm) >= 0:
                    log.info("Wake word detected")
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
            beam_size=1,  # fastest; bump to 5 if accuracy matters more
            vad_filter=False,  # webrtcvad already handled endpointing
        )
        return " ".join(s.text for s in segments).strip()

    def close(self) -> None:
        if self.porcupine is not None:
            self.porcupine.delete()
