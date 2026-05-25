"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        audio/wake_word.py
Purpose:     Local wake word detection using the Porcupine engine (Picovoice).
             Audio is processed entirely on-device. No audio data is transmitted
             to any external service during wake word detection. Only after a
             confirmed wake word event does the system begin streaming audio
             to River Song for command processing.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================

Privacy guarantee:
    This module NEVER sends audio to any network endpoint. It reads raw PCM
    frames from the microphone, passes them to the local Porcupine library,
    and emits a callback when the wake word is detected. The audio frames
    themselves are discarded after each Porcupine process() call.
    Audio streaming to River Song is handled exclusively by AudioManager
    after this module fires its on_wake_word callback.
"""

import logging
import threading
from typing import Callable, Optional

from core.config import config
from core.constants import (
    AUDIO_CHUNK_SIZE,
    DEFAULT_WAKE_WORD,
    PORCUPINE_MODEL_DIR,
    SAMPLE_RATE,
    WAKE_WORD_COOLDOWN_SECONDS,
    WAKE_WORD_SENSITIVITY,
)

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """
    Local, on-device wake word detector powered by Porcupine (Picovoice).

    Runs in a dedicated background thread. When the configured wake word
    is detected, the registered callback is invoked on that thread.

    Privacy contract:
        - Audio frames are processed locally by pvporcupine.
        - No audio data is written to disk or sent over the network.
        - The callback receives no audio data — only a detection event.

    Usage:
        detector = WakeWordDetector(on_wake_word=my_callback)
        detector.start()
        # ... later ...
        detector.stop()
    """

    def __init__(
        self,
        on_wake_word: Callable[[], None],
        sensitivity: Optional[float] = None,
    ) -> None:
        """
        Initialize the wake word detector.

        Args:
            on_wake_word: Callback invoked (no arguments) when the wake word
                          is detected. Called from the detector thread.
            sensitivity:  Detection sensitivity in [0.0, 1.0]. Higher values
                          increase recall but also false-positive rate.
                          Defaults to WAKE_WORD_SENSITIVITY from constants.
        """
        self._on_wake_word: Callable[[], None] = on_wake_word
        self._sensitivity: float = sensitivity or config.get(
            "wake_word_sensitivity", WAKE_WORD_SENSITIVITY
        )
        self._wake_word: str = config.get("wake_word", DEFAULT_WAKE_WORD)
        self._access_key: str = config.get("porcupine_access_key", "")

        self._porcupine = None          # pvporcupine.Porcupine instance
        self._audio_stream = None       # PyAudio stream
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._last_detection_time: float = 0.0

    def start(self) -> None:
        """
        Initialize Porcupine and start the detection thread.

        Raises:
            RuntimeError: If Porcupine cannot be initialized (e.g., invalid
                          access key or unsupported wake word).
        """
        if self._running:
            logger.warning("WakeWordDetector is already running.")
            return

        if not self._access_key:
            logger.error(
                "Porcupine access key is not configured. "
                "Wake word detection is disabled. "
                "Set PORCUPINE_ACCESS_KEY in your environment."
            )
            return

        self._init_porcupine()
        self._running = True
        self._thread = threading.Thread(
            target=self._detection_loop,
            name="wake-word-detector",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Wake word detector started. Listening for '%s' (sensitivity=%.2f).",
            self._wake_word,
            self._sensitivity,
        )

    def stop(self) -> None:
        """
        Stop the detection thread and release Porcupine resources.

        Safe to call even if start() was never called or already stopped.
        """
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._cleanup()
        logger.info("Wake word detector stopped.")

    def is_running(self) -> bool:
        """Return True if the detection thread is active."""
        return self._running and (self._thread is not None) and self._thread.is_alive()

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    def _init_porcupine(self) -> None:
        """
        Create the Porcupine instance for the configured wake word.

        Uses the built-in keyword if the wake word matches a Porcupine
        built-in; otherwise loads a custom .ppn model file from
        PORCUPINE_MODEL_DIR.

        Raises:
            RuntimeError: On Porcupine initialization failure.
        """
        try:
            import pvporcupine  # type: ignore

            # Porcupine built-in keywords (subset — check pvporcupine docs for full list)
            builtin_keywords = pvporcupine.KEYWORDS

            if self._wake_word.lower() in builtin_keywords:
                self._porcupine = pvporcupine.create(
                    access_key=self._access_key,
                    keywords=[self._wake_word.lower()],
                    sensitivities=[self._sensitivity],
                )
                logger.debug("Porcupine initialized with built-in keyword '%s'.", self._wake_word)
            else:
                # Custom wake word — look for a .ppn file
                import os
                model_path = os.path.join(PORCUPINE_MODEL_DIR, f"{self._wake_word}.ppn")
                if not os.path.exists(model_path):
                    raise RuntimeError(
                        f"Custom wake word model not found: {model_path}. "
                        f"Train a custom model at console.picovoice.ai and place "
                        f"the .ppn file in {PORCUPINE_MODEL_DIR}."
                    )
                self._porcupine = pvporcupine.create(
                    access_key=self._access_key,
                    keyword_paths=[model_path],
                    sensitivities=[self._sensitivity],
                )
                logger.debug("Porcupine initialized with custom model '%s'.", model_path)

        except ImportError:
            raise RuntimeError(
                "pvporcupine is not installed. "
                "Install it with: pip install pvporcupine"
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize Porcupine: {exc}") from exc

    def _detection_loop(self) -> None:
        """
        Main detection loop. Reads PCM frames from the microphone and
        passes them to Porcupine for wake word detection.

        Runs on the detector thread until stop() is called.
        Privacy note: audio frames are never stored or transmitted here.
        """
        import time

        try:
            import pyaudio  # type: ignore

            pa = pyaudio.PyAudio()
            device_index = config.get("audio_device_index", -1)
            stream_kwargs = dict(
                rate=SAMPLE_RATE,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self._porcupine.frame_length,
            )
            if device_index >= 0:
                stream_kwargs["input_device_index"] = device_index

            self._audio_stream = pa.open(**stream_kwargs)
            logger.debug("Porcupine audio stream opened (frame_length=%d).",
                         self._porcupine.frame_length)

            while self._running:
                try:
                    raw = self._audio_stream.read(
                        self._porcupine.frame_length,
                        exception_on_overflow=False,
                    )
                except OSError as exc:
                    logger.warning("Audio read error in wake word loop: %s", exc)
                    continue

                # Unpack raw bytes to int16 PCM samples
                import struct
                pcm = struct.unpack_from(
                    f"{self._porcupine.frame_length}h", raw
                )

                result = self._porcupine.process(pcm)
                if result >= 0:
                    now = time.monotonic()
                    if now - self._last_detection_time >= WAKE_WORD_COOLDOWN_SECONDS:
                        self._last_detection_time = now
                        logger.info("Wake word '%s' detected.", self._wake_word)
                        self._fire_callback()

        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Wake word detection loop crashed: %s", exc, exc_info=True)
        finally:
            if self._audio_stream:
                try:
                    self._audio_stream.stop_stream()
                    self._audio_stream.close()
                except Exception:  # pylint: disable=broad-except
                    pass
            logger.debug("Wake word detection loop exited.")

    def _fire_callback(self) -> None:
        """
        Invoke the on_wake_word callback safely.

        Exceptions raised by the callback are caught and logged so they
        cannot crash the detection thread.
        """
        try:
            self._on_wake_word()
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Exception in on_wake_word callback: %s", exc, exc_info=True)

    def _cleanup(self) -> None:
        """Release Porcupine and PyAudio resources."""
        if self._porcupine:
            try:
                self._porcupine.delete()
            except Exception:  # pylint: disable=broad-except
                pass
            self._porcupine = None

        if self._audio_stream:
            try:
                self._audio_stream.stop_stream()
                self._audio_stream.close()
            except Exception:  # pylint: disable=broad-except
                pass
            self._audio_stream = None
