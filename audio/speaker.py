"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        audio/speaker.py
Purpose:     Speaker output management. Handles TTS audio playback, volume
             control, audio queuing, and wake word confirmation chimes.
             Receives audio data from AudioManager — does not generate speech.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import io
import logging
import queue
import threading
from pathlib import Path
from typing import Optional, Union

from core.config import config
from core.constants import (
    DEFAULT_VOLUME,
    INTERCOM_AUDIO_CHANNELS,
    INTERCOM_AUDIO_SAMPLE_RATE,
    MAX_VOLUME,
    MIN_VOLUME,
    SPEAKER_CHANNELS,
    SPEAKER_SAMPLE_RATE,
    TTS_CACHE_DIR,
)

logger = logging.getLogger(__name__)


class SpeakerError(Exception):
    """Raised when audio playback fails."""
    pass


class Speaker:
    """
    Manages audio output for River Vortex.

    Supports:
    - Queued playback of TTS audio (bytes or file path)
    - Volume control (0–100)
    - Playback interruption for urgent responses
    - Wake word confirmation chime
    - Non-blocking play via background thread

    AudioManager is the primary caller. Do not call Speaker directly
    from other subsystems — route through AudioManager.
    """

    def __init__(self) -> None:
        """Initialize the Speaker. Does not open hardware yet."""
        self._volume: int = config.get("volume", DEFAULT_VOLUME)
        self._playback_queue: queue.Queue = queue.Queue()
        self._playback_thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._current_playback_stop = threading.Event()

        # Persistent raw PCM output stream — used for low-latency intercom
        # audio, which arrives as headerless frames (see play_raw()).
        self._raw_stream = None
        self._raw_pa = None
        self._raw_stream_params: Optional[tuple] = None

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """
        Start the background playback thread.

        The thread processes the playback queue continuously until stop() is called.
        """
        if self._running:
            return
        self._running = True
        self._playback_thread = threading.Thread(
            target=self._playback_loop,
            name="speaker-playback",
            daemon=True,
        )
        self._playback_thread.start()
        logger.info("Speaker started (volume=%d%%).", self._volume)

    def stop(self) -> None:
        """
        Stop the playback thread and drain the queue.

        Any audio currently playing is interrupted.
        """
        self._running = False
        self._current_playback_stop.set()
        # Unblock the queue.get() in the playback loop
        self._playback_queue.put(None)
        if self._playback_thread and self._playback_thread.is_alive():
            self._playback_thread.join(timeout=3.0)
        self.stop_raw()
        logger.info("Speaker stopped.")

    # ─────────────────────────────────────────────────────────────────────────
    # Playback API
    # ─────────────────────────────────────────────────────────────────────────

    def play(self, audio: Union[bytes, str, Path], interrupt: bool = False) -> None:
        """
        Queue audio for playback.

        Args:
            audio:     Raw audio bytes (WAV/MP3), or a path to an audio file.
            interrupt: If True, stop current playback and play this immediately.
        """
        if interrupt:
            self._current_playback_stop.set()
            # Drain the queue
            while not self._playback_queue.empty():
                try:
                    self._playback_queue.get_nowait()
                except queue.Empty:
                    break

        self._playback_queue.put(audio)
        logger.debug("Audio queued for playback (interrupt=%s).", interrupt)

    def play_chime(self, chime_type: str = "wake") -> None:
        """
        Play a short system chime.

        Args:
            chime_type: One of 'wake' (wake word confirmed), 'done' (command processed),
                        'error' (command failed), 'intercom' (incoming intercom call).
        """
        chime_paths = {
            "wake":     "audio/chimes/wake.wav",
            "done":     "audio/chimes/done.wav",
            "error":    "audio/chimes/error.wav",
            "intercom": "audio/chimes/intercom.wav",
        }
        path = chime_paths.get(chime_type)
        if path and Path(path).exists():
            self.play(path, interrupt=False)
        else:
            logger.debug("Chime '%s' not found at '%s' — skipping.", chime_type, path)

    def play_raw(
        self,
        pcm_bytes: bytes,
        sample_rate: int = INTERCOM_AUDIO_SAMPLE_RATE,
        channels: int = INTERCOM_AUDIO_CHANNELS,
    ) -> None:
        """
        Play a headerless raw PCM16 audio frame immediately via a persistent
        output stream — used for low-latency intercom audio, which arrives
        as small frames that cannot go through the WAV-based play() queue.

        Args:
            pcm_bytes:   Raw PCM bytes (int16).
            sample_rate: Sample rate of `pcm_bytes` in Hz.
            channels:    Channel count of `pcm_bytes`.
        """
        try:
            self._open_raw_stream(sample_rate, channels)
            self._raw_stream.write(self._apply_volume(pcm_bytes))
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Failed to play raw audio frame: %s", exc)

    def stop_raw(self) -> None:
        """Stop and release the persistent raw PCM output stream, if open."""
        if self._raw_stream:
            try:
                self._raw_stream.stop_stream()
                self._raw_stream.close()
            except Exception:  # pylint: disable=broad-except
                pass
            self._raw_stream = None
        if self._raw_pa:
            try:
                self._raw_pa.terminate()
            except Exception:  # pylint: disable=broad-except
                pass
            self._raw_pa = None
        self._raw_stream_params = None

    def set_volume(self, level: int) -> None:
        """
        Set the playback volume.

        Args:
            level: Volume level from MIN_VOLUME (0) to MAX_VOLUME (100).
        """
        self._volume = max(MIN_VOLUME, min(MAX_VOLUME, level))
        logger.info("Volume set to %d%%.", self._volume)

    def get_volume(self) -> int:
        """Return the current volume level (0–100)."""
        return self._volume

    def is_playing(self) -> bool:
        """Return True if audio is currently being played."""
        return not self._playback_queue.empty() or not self._current_playback_stop.is_set()

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    def _playback_loop(self) -> None:
        """
        Background thread loop. Dequeues audio items and plays them sequentially.

        Runs until stop() is called (sentinel None is enqueued).
        """
        while self._running:
            try:
                item = self._playback_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if item is None:
                break  # Shutdown sentinel

            self._current_playback_stop.clear()
            try:
                self._play_item(item)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Playback error: %s", exc)

    def _open_raw_stream(self, sample_rate: int, channels: int) -> None:
        """
        Lazily (re)open the persistent raw PCM output stream.

        A no-op if a stream is already open with matching parameters.
        """
        if self._raw_stream and self._raw_stream_params == (sample_rate, channels):
            return

        if self._raw_stream:
            self.stop_raw()

        import pyaudio  # type: ignore

        self._raw_pa = self._raw_pa or pyaudio.PyAudio()
        self._raw_stream = self._raw_pa.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=sample_rate,
            output=True,
        )
        self._raw_stream_params = (sample_rate, channels)

    def _play_item(self, audio: Union[bytes, str, Path]) -> None:
        """
        Play a single audio item (bytes or file path).

        Args:
            audio: Raw audio bytes or path to an audio file.
        """
        try:
            import pyaudio  # type: ignore
            import wave

            # Resolve audio source to bytes
            if isinstance(audio, (str, Path)):
                audio_path = Path(audio)
                if not audio_path.exists():
                    logger.warning("Audio file not found: %s", audio_path)
                    return
                with audio_path.open("rb") as fh:
                    audio_bytes = fh.read()
            else:
                audio_bytes = audio

            # Apply volume scaling
            audio_bytes = self._apply_volume(audio_bytes)

            # Play via PyAudio
            buf = io.BytesIO(audio_bytes)
            with wave.open(buf, "rb") as wf:
                pa = pyaudio.PyAudio()
                stream = pa.open(
                    format=pa.get_format_from_width(wf.getsampwidth()),
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    output=True,
                )
                chunk_size = 1024
                data = wf.readframes(chunk_size)
                while data and not self._current_playback_stop.is_set():
                    stream.write(data)
                    data = wf.readframes(chunk_size)
                stream.stop_stream()
                stream.close()
                pa.terminate()

        except Exception as exc:
            raise SpeakerError(f"Failed to play audio: {exc}") from exc

    def _apply_volume(self, audio_bytes: bytes) -> bytes:
        """
        Scale PCM audio amplitude by the current volume level.

        Args:
            audio_bytes: Raw PCM bytes (int16).

        Returns:
            Volume-adjusted PCM bytes.
        """
        import struct
        import array

        if self._volume == 100:
            return audio_bytes

        scale = self._volume / 100.0
        samples = array.array("h", audio_bytes)
        scaled = array.array("h", (int(s * scale) for s in samples))
        return scaled.tobytes()
