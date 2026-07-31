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
        # True only while _play_item is actually pushing frames to the device.
        self._playing: bool = False

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
        """
        Return True if audio is queued or actively playing.

        Note: _current_playback_stop is an interrupt flag, not a "playing"
        flag — it is unset at rest, so testing it here would report True
        whenever the speaker was idle.
        """
        return self._playing or not self._playback_queue.empty()

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
            self._playing = True
            try:
                self._play_item(item)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Playback error: %s", exc)
            finally:
                self._playing = False

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

            # Play via PyAudio.
            #
            # Volume is applied per-frame BELOW, not to the whole byte string.
            # Scaling the entire WAV would corrupt the 44-byte RIFF header
            # along with the samples, and wave.open() would then reject it.
            buf = io.BytesIO(audio_bytes)
            with wave.open(buf, "rb") as wf:
                sample_width = wf.getsampwidth()
                pa = pyaudio.PyAudio()
                stream = pa.open(
                    format=pa.get_format_from_width(sample_width),
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    output=True,
                )
                chunk_size = 1024
                data = wf.readframes(chunk_size)
                while data and not self._current_playback_stop.is_set():
                    stream.write(self._apply_volume(data, sample_width))
                    data = wf.readframes(chunk_size)
                stream.stop_stream()
                stream.close()
                pa.terminate()

        except Exception as exc:
            raise SpeakerError(f"Failed to play audio: {exc}") from exc

    def _apply_volume(self, pcm_frames: bytes, sample_width: int = 2) -> bytes:
        """
        Scale raw PCM frame amplitude by the current volume level.

        Takes PCM FRAMES ONLY — never a whole WAV file. Passing a full WAV
        here would scale the RIFF header bytes as if they were samples and
        produce an unplayable stream.

        Args:
            pcm_frames:   Raw PCM frame bytes (no container header).
            sample_width: Bytes per sample. Only 16-bit (2) is scaled;
                          other widths are passed through untouched.

        Returns:
            Volume-adjusted PCM bytes.
        """
        import array

        if self._volume == 100 or not pcm_frames:
            return pcm_frames

        # array('h') requires 16-bit samples and an even byte count. A partial
        # final frame would raise, so pass anything unexpected through rather
        # than dropping audio.
        if sample_width != 2 or len(pcm_frames) % 2 != 0:
            return pcm_frames

        scale = self._volume / 100.0
        samples = array.array("h", pcm_frames)
        for i, sample in enumerate(samples):
            # Clamp to int16 range — scale is <= 1.0 so this is belt-and-braces.
            samples[i] = max(-32768, min(32767, int(sample * scale)))
        return samples.tobytes()
