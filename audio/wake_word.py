"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        audio/wake_word.py
Purpose:     Local wake word detection using openWakeWord.

             Replaces Porcupine, for two reasons. Porcupine needs a Picovoice
             access key — a commercial licence dependency in the one part of
             the system that is meant to prove nothing leaves the house — and
             River Song already uses openWakeWord, so the two halves disagreed
             about what "hey River" even means.

             The wake word itself is chosen in the user's River Song profile
             and arrives in the replica payload. This module just loads
             whatever model it has been told to listen for.
Author:      [Author Placeholder]
Version:     2.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================

Privacy guarantee:
    This module NEVER sends audio anywhere. It reads raw PCM frames from the
    microphone, scores them against a local model file, and emits a callback
    on detection. The frames are discarded after each prediction, and the
    callback carries no audio.

    Model files are loaded from disk only. openWakeWord can download its
    pretrained models on first use; that is deliberately disabled here,
    because a unit that quietly fetches a model the first time someone speaks
    to it is not a unit that keeps its promise.
"""

import logging
import os
import threading
import time
from typing import Any, Callable, List, Optional

from core.config import config
from core.constants import (
    DEFAULT_WAKE_WORD,
    SAMPLE_RATE,
    WAKE_WORD_COOLDOWN_SECONDS,
    WAKE_WORD_FRAME_LENGTH,
    WAKE_WORD_MODEL_DIR,
    WAKE_WORD_THRESHOLD,
)

logger = logging.getLogger(__name__)

#: File extensions openWakeWord can load, in preference order. ONNX first —
#: it is the better-supported runtime on a Pi 4.
MODEL_EXTENSIONS = (".onnx", ".tflite")


def model_name_for(phrase: str) -> str:
    """
    Turn a spoken wake word into the model filename that implements it.

    River Song stores the phrase as the user typed it — "Hey River", "sup
    river" — and models are named on disk in snake case. Normalising here
    means the profile can hold something human and the filesystem something
    predictable.

    Args:
        phrase: The wake word as configured.

    Returns:
        A bare model name with no extension, e.g. "hey_river".
    """
    cleaned = "".join(c if c.isalnum() else " " for c in (phrase or "").lower())
    return "_".join(cleaned.split()) or DEFAULT_WAKE_WORD


def available_models(directory: Optional[str] = None) -> List[str]:
    """
    List the wake word models present on this unit.

    Args:
        directory: Where to look. Defaults to the configured model directory.

    Returns:
        Bare model names, without extension, sorted.
    """
    directory = directory or config.get("wake_word_model_dir", WAKE_WORD_MODEL_DIR)
    try:
        entries = os.listdir(directory)
    except OSError:
        return []
    return sorted({
        os.path.splitext(name)[0] for name in entries
        if name.endswith(MODEL_EXTENSIONS)
    })


class WakeWordDetector:
    """
    Local, on-device wake word detector powered by openWakeWord.

    Runs in a dedicated background thread. When the configured wake word is
    detected, the registered callback is invoked on that thread.

    Privacy contract:
        - Audio frames are scored locally against a model file on disk.
        - No audio is written to disk or sent over the network.
        - The callback receives no audio data — only a detection event.
        - No licence key, no account, no phone-home.

    Usage:
        detector = WakeWordDetector(on_wake_word=my_callback)
        detector.start()
        ...
        detector.stop()
    """

    def __init__(
        self,
        on_wake_word: Callable[[], None],
        threshold: Optional[float] = None,
        privacy_manager: Any = None,
    ) -> None:
        """
        Initialize the wake word detector.

        Args:
            on_wake_word: Callback invoked (no arguments) on detection. Called
                          from the detector thread.
            privacy_manager: The mute authority. This detector opens its OWN
                          audio stream, separate from the Microphone, so
                          without this a muted unit would still wake to its
                          name — which is not what anyone means by muted.
            threshold:    Confidence in [0.0, 1.0] above which a frame counts
                          as a detection. HIGHER IS STRICTER — the inverse of
                          Porcupine's old sensitivity dial, so a value carried
                          over from the previous config will behave backwards.
        """
        self._on_wake_word: Callable[[], None] = on_wake_word
        self._privacy = privacy_manager
        self._threshold: float = threshold if threshold is not None else float(
            config.get("wake_word_threshold", WAKE_WORD_THRESHOLD)
        )
        self._phrase: str = config.get("wake_word", DEFAULT_WAKE_WORD)
        self._model_name: str = model_name_for(self._phrase)
        self._model_dir: str = config.get("wake_word_model_dir", WAKE_WORD_MODEL_DIR)

        self._model = None              # openwakeword.model.Model
        self._audio_stream = None       # PyAudio stream
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._last_detection_time: float = 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """
        Load the model and start the detection thread.

        A missing model is logged and leaves the unit without wake word
        detection, rather than raising: the panel should still show the clock
        and answer the touchscreen. The boot self-test reports the gap.
        """
        if self._running:
            logger.warning("WakeWordDetector is already running.")
            return

        try:
            self._load_model()
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Wake word detection unavailable: %s", exc)
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._detection_loop,
            name="wake-word-detector",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Wake word detector started. Listening for '%s' (model=%s, threshold=%.2f).",
            self._phrase, self._model_name, self._threshold,
        )

    def stop(self) -> None:
        """Stop the detection thread and release resources."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._cleanup()
        logger.info("Wake word detector stopped.")

    def is_running(self) -> bool:
        """Return True if the detection thread is active."""
        return self._running and (self._thread is not None) and self._thread.is_alive()

    @property
    def threshold(self) -> float:
        """Confidence a frame must reach to count as a detection."""
        return self._threshold

    def set_threshold(self, value: Any) -> bool:
        """
        Retune how eagerly this unit wakes.

        This is the dial that actually gets touched in a real house. A kitchen
        panel beside a dishwasher wakes at every clatter; a bedroom one across
        the room mishears nothing but also hears nothing. It is per unit for
        exactly that reason.

        Takes effect immediately — the detection loop reads the threshold on
        every frame, so there is nothing to restart.

        Args:
            value: New threshold. Higher is stricter (fewer false wakes,
                more missed ones). Values outside 0..1 are refused rather
                than clamped: 5 almost certainly means someone thought this
                was the old sensitivity scale, and silently turning that into
                1.0 would leave a unit that never wakes and no clue why.

        Returns:
            True if the threshold changed.
        """
        try:
            threshold = float(value)
        except (TypeError, ValueError):
            logger.warning("Ignoring non-numeric wake word threshold %r.", value)
            return False

        if not 0.0 <= threshold <= 1.0:
            logger.warning(
                "Ignoring wake word threshold %.2f — it must be between 0 and 1. "
                "Note this is NOT the old Porcupine sensitivity scale; higher "
                "is now stricter.", threshold,
            )
            return False

        if threshold == self._threshold:
            return False

        logger.info("Wake word threshold changed from %.2f to %.2f.",
                    self._threshold, threshold)
        self._threshold = threshold
        return True

    async def set_wake_word(self, phrase: str) -> bool:
        """
        Change the wake word this unit listens for.

        River Song owns the choice, so this is called when the replica payload
        brings a phrase different from the one currently loaded — a user
        changing it in their profile should take effect without reflashing a
        unit or rebooting it.

        Args:
            phrase: The new wake word.

        Returns:
            True if the unit is now listening for it. False means the model is
            not on this unit, in which case the OLD wake word stays active —
            better a unit that answers to the wrong phrase than one that
            answers to nothing.
        """
        name = model_name_for(phrase)
        if name == self._model_name:
            return True

        if not self._find_model_file(name):
            logger.warning(
                "River Song asked for wake word '%s' but no model '%s' is on "
                "this unit; still listening for '%s'. Available: %s",
                phrase, name, self._phrase, ", ".join(available_models(self._model_dir)) or "none",
            )
            return False

        logger.info("Wake word changing from '%s' to '%s'.", self._phrase, phrase)
        was_running = self.is_running()
        self.stop()
        self._phrase = phrase
        self._model_name = name
        if was_running:
            self.start()
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    def _find_model_file(self, name: str) -> Optional[str]:
        """Return the path to a model on disk, or None if it is not here."""
        for extension in MODEL_EXTENSIONS:
            path = os.path.join(self._model_dir, f"{name}{extension}")
            if os.path.exists(path):
                return path
        return None

    def _load_model(self) -> None:
        """
        Load the wake word model from disk.

        Raises:
            RuntimeError: If openWakeWord is missing or the model is not on
                this unit.
        """
        try:
            from openwakeword.model import Model  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "openwakeword is not installed. Install it with: "
                "pip install openwakeword"
            ) from exc

        path = self._find_model_file(self._model_name)
        if not path:
            raise RuntimeError(
                f"No wake word model '{self._model_name}' in {self._model_dir}. "
                f"Available: {', '.join(available_models(self._model_dir)) or 'none'}. "
                f"Models are baked into the unit image, not downloaded at runtime."
            )

        framework = "onnx" if path.endswith(".onnx") else "tflite"
        self._model = Model(wakeword_models=[path], inference_framework=framework)
        logger.debug("Loaded wake word model %s (%s).", path, framework)

    def _detection_loop(self) -> None:
        """
        Read PCM frames from the microphone and score them locally.

        Runs on the detector thread until stop() is called. Audio frames are
        never stored or transmitted here.
        """
        try:
            import numpy as np  # type: ignore
            import pyaudio  # type: ignore

            pa = pyaudio.PyAudio()
            device_index = config.get("audio_device_index", -1)
            stream_kwargs = dict(
                rate=SAMPLE_RATE,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=WAKE_WORD_FRAME_LENGTH,
            )
            if device_index >= 0:
                stream_kwargs["input_device_index"] = device_index

            self._audio_stream = pa.open(**stream_kwargs)
            logger.debug("Wake word audio stream opened (frame=%d samples).",
                         WAKE_WORD_FRAME_LENGTH)

            while self._running:
                try:
                    raw = self._audio_stream.read(
                        WAKE_WORD_FRAME_LENGTH, exception_on_overflow=False,
                    )
                except OSError as exc:
                    logger.warning("Audio read error in wake word loop: %s", exc)
                    continue

                # Checked after the read so the stream keeps draining — a
                # backed-up buffer would deliver stale audio the moment the
                # switch came off — but before anything is scored, so muted
                # audio is never examined for the wake word at all.
                if self._is_muted():
                    continue

                frame = np.frombuffer(raw, dtype=np.int16)
                scores = self._model.predict(frame)
                if self._is_detection(scores):
                    self._maybe_fire()

        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Wake word detection loop crashed: %s", exc, exc_info=True)
        finally:
            self._close_stream()
            logger.debug("Wake word detection loop exited.")

    def _is_muted(self) -> bool:
        """
        Whether this unit is currently muted, by software or by the switch.

        Asked on every frame rather than cached: the point of the physical
        switch is that flipping it takes effect now, and a cached answer is a
        thing that can be wrong for as long as the cache lasts.
        """
        try:
            return bool(self._privacy is not None and self._privacy.mic_muted)
        except Exception:  # pylint: disable=broad-except
            # Fail towards NOT muted: a broken privacy manager should not
            # silently deafen a unit with no way for the user to tell why.
            # The LED and the settings screen both still report the truth.
            return False

    def _is_detection(self, scores) -> bool:
        """
        Whether this frame's scores cross the threshold.

        openWakeWord returns a dict keyed by model name. Only one model is
        loaded, but the key is whatever it derived from the file path, so the
        values are checked rather than looked up by name — a key that does not
        match would otherwise silently never fire.
        """
        try:
            return any(float(score) >= self._threshold for score in scores.values())
        except (AttributeError, TypeError, ValueError):
            return False

    def _maybe_fire(self) -> None:
        """Fire the callback unless we are still inside the cooldown window."""
        now = time.monotonic()
        if now - self._last_detection_time < WAKE_WORD_COOLDOWN_SECONDS:
            return
        self._last_detection_time = now
        logger.info("Wake word '%s' detected.", self._phrase)
        try:
            self._on_wake_word()
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Exception in on_wake_word callback: %s", exc, exc_info=True)

    def _close_stream(self) -> None:
        if self._audio_stream:
            try:
                self._audio_stream.stop_stream()
                self._audio_stream.close()
            except Exception:  # pylint: disable=broad-except
                pass
            self._audio_stream = None

    def _cleanup(self) -> None:
        """Release the model and audio resources."""
        self._model = None
        self._close_stream()
