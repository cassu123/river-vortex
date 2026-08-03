"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        audio/microphone.py
Purpose:     Microphone input management. Provides raw PCM audio capture,
             device enumeration, and a streaming interface used by AudioManager
             to forward command audio to River Song after wake word detection.
             This module handles hardware I/O only — no AI, no wake word logic.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
import queue
import threading
from typing import Callable, Generator, List, Optional

from core.config import config
from core.constants import (
    AUDIO_CHANNELS,
    AUDIO_CHUNK_SIZE,
    AUDIO_FORMAT_BITS,
    SAMPLE_RATE,
    SILENCE_THRESHOLD_RMS,
    SILENCE_TIMEOUT_SECONDS,
    MAX_COMMAND_DURATION_SECONDS,
)

logger = logging.getLogger(__name__)


class MicrophoneError(Exception):
    """Raised when the microphone cannot be opened or read."""
    pass


class Microphone:
    """
    Manages the physical microphone input stream.

    Provides:
    - Device enumeration (list_devices)
    - Blocking frame capture (read_frame)
    - Non-blocking streaming with silence detection (stream_until_silence)
    - Mute/unmute control

    This class is not responsible for wake word detection or audio routing.
    AudioManager coordinates those concerns.
    """

    def __init__(self) -> None:
        """Initialize the Microphone. Does not open the hardware stream yet."""
        self._device_index: int = config.get("audio_device_index", -1)
        self._sample_rate: int = SAMPLE_RATE
        self._channels: int = AUDIO_CHANNELS
        self._chunk_size: int = AUDIO_CHUNK_SIZE
        self._muted: bool = False
        # The privacy manager, when one exists. Consulted on every frame read
        # rather than mirrored into a local flag, because a copy is a thing
        # that can be stale — and a microphone that is stale about being muted
        # is the exact failure this whole subsystem exists to prevent.
        self._privacy = None

        self._pa = None             # PyAudio instance
        self._stream = None         # Active PyAudio stream
        self._lock = threading.Lock()

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def open(self) -> None:
        """
        Open the microphone hardware stream.

        Raises:
            MicrophoneError: If PyAudio cannot open the requested device.
        """
        try:
            import pyaudio  # type: ignore
            self._pa = pyaudio.PyAudio()
            kwargs = dict(
                format=pyaudio.paInt16,
                channels=self._channels,
                rate=self._sample_rate,
                input=True,
                frames_per_buffer=self._chunk_size,
            )
            if self._device_index >= 0:
                kwargs["input_device_index"] = self._device_index

            self._stream = self._pa.open(**kwargs)
            logger.info(
                "Microphone opened: device=%s, rate=%d, channels=%d, chunk=%d",
                self._device_index if self._device_index >= 0 else "default",
                self._sample_rate,
                self._channels,
                self._chunk_size,
            )
        except Exception as exc:
            raise MicrophoneError(f"Failed to open microphone: {exc}") from exc

    def close(self) -> None:
        """Close the microphone stream and release PyAudio resources."""
        with self._lock:
            if self._stream:
                try:
                    self._stream.stop_stream()
                    self._stream.close()
                except Exception:  # pylint: disable=broad-except
                    pass
                self._stream = None
            if self._pa:
                try:
                    self._pa.terminate()
                except Exception:  # pylint: disable=broad-except
                    pass
                self._pa = None
        logger.info("Microphone closed.")

    def read_frame(self) -> bytes:
        """
        Read one chunk of raw PCM audio from the microphone.

        Returns:
            Raw PCM bytes (int16, mono, SAMPLE_RATE Hz).

        Raises:
            MicrophoneError: If the stream is not open or a read error occurs.
        """
        if not self._stream:
            raise MicrophoneError("Microphone stream is not open. Call open() first.")
        if self.muted:
            # Return silence when muted — same byte length as a real frame
            return b"\x00" * (self._chunk_size * 2)  # 2 bytes per int16 sample
        try:
            return self._stream.read(self._chunk_size, exception_on_overflow=False)
        except OSError as exc:
            raise MicrophoneError(f"Microphone read error: {exc}") from exc

    def stream_until_silence(
        self,
        max_duration: float = MAX_COMMAND_DURATION_SECONDS,
        silence_timeout: float = SILENCE_TIMEOUT_SECONDS,
        silence_threshold: int = SILENCE_THRESHOLD_RMS,
    ) -> Generator[bytes, None, None]:
        """
        Yield PCM audio chunks until silence is detected or max_duration is reached.

        Used by AudioManager to capture a voice command after wake word detection.
        The generator stops when:
          - `silence_timeout` seconds of audio below `silence_threshold` RMS
          - `max_duration` seconds of total audio have been captured

        Args:
            max_duration:      Hard cap on total capture time (seconds).
            silence_timeout:   Seconds of silence before stopping.
            silence_threshold: RMS amplitude below which audio is considered silence.

        Yields:
            Raw PCM bytes for each captured chunk.
        """
        import time
        import struct
        import math

        if not self._stream:
            raise MicrophoneError("Microphone stream is not open.")

        # Muted means muted. This path reads the hardware stream directly for
        # speed, which meant it bypassed the mute check entirely — so a muted
        # microphone would still have captured a command and sent it upstream.
        # Yield nothing rather than silence: a silent command is still a
        # command, and still leaves the house.
        if self.muted:
            logger.info("Command capture refused — the microphone is muted.")
            return

        start_time = time.monotonic()
        silence_start: Optional[float] = None

        logger.debug("Streaming audio for command capture (max=%.1fs).", max_duration)

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= max_duration:
                logger.debug("Command capture hit max duration (%.1fs).", max_duration)
                break

            # Re-checked every chunk, not just at the start: someone hitting
            # mute mid-sentence expects the rest of that sentence not to go.
            if self.muted:
                logger.info("Command capture stopped — microphone muted mid-capture.")
                break

            try:
                chunk = self._stream.read(self._chunk_size, exception_on_overflow=False)
            except OSError as exc:
                logger.warning("Microphone read error during streaming: %s", exc)
                break

            # Calculate RMS to detect silence
            samples = struct.unpack(f"{len(chunk) // 2}h", chunk)
            rms = math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0

            if rms < silence_threshold:
                if silence_start is None:
                    silence_start = time.monotonic()
                elif time.monotonic() - silence_start >= silence_timeout:
                    logger.debug("Silence detected — ending command capture.")
                    break
            else:
                silence_start = None  # Reset silence timer on speech

            yield chunk

    def set_privacy_manager(self, privacy_manager) -> None:
        """
        Attach the privacy manager whose mute state this microphone obeys.

        Until this was wired, PrivacyManager.mute_microphone() set a flag and
        lit an LED and blocked nothing: the Microphone had its own separate
        flag that only AudioManager ever touched. A privacy control that
        reports "muted" while audio keeps flowing is worse than none, because
        it is believed.
        """
        self._privacy = privacy_manager

    @property
    def muted(self) -> bool:
        """
        True if this microphone is muted, by any means.

        Either the local software flag or the privacy manager — which itself
        answers for the physical switch. Any one of them muting is enough;
        none of them can un-mute on another's behalf.
        """
        if self._muted:
            return True
        return bool(self._privacy is not None and self._privacy.mic_muted)

    def mute(self) -> None:
        """
        Mute the microphone in software.

        read_frame() will return silence frames while muted.
        For hardware mute (LED indicator), see safety/privacy_manager.py.
        """
        self._muted = True
        logger.info("Microphone muted (software).")

    def unmute(self) -> None:
        """Unmute the microphone."""
        self._muted = False
        logger.info("Microphone unmuted.")

    @property
    def is_muted(self) -> bool:
        """Return True if the microphone is currently muted."""
        return self._muted

    @property
    def is_open(self) -> bool:
        """Return True if the hardware stream is open."""
        return self._stream is not None

    @staticmethod
    def list_devices() -> List[dict]:
        """
        Enumerate available audio input devices.

        Returns:
            List of dicts with keys: index, name, max_input_channels, default_sample_rate.
        """
        try:
            import pyaudio  # type: ignore
            pa = pyaudio.PyAudio()
            devices = []
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    devices.append({
                        "index": i,
                        "name": info.get("name", "Unknown"),
                        "max_input_channels": info.get("maxInputChannels"),
                        "default_sample_rate": info.get("defaultSampleRate"),
                    })
            pa.terminate()
            return devices
        except Exception as exc:
            logger.error("Failed to enumerate audio devices: %s", exc)
            return []
