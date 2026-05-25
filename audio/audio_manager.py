"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        audio/audio_manager.py
Purpose:     Top-level audio subsystem coordinator. Owns the wake word detector,
             microphone, and speaker. Orchestrates the full voice command flow:
               1. Wake word detected locally (Porcupine — no cloud)
               2. Play confirmation chime
               3. Stream audio to River Song API
               4. Receive TTS response
               5. Play response through speaker
             This is the only module that initiates audio streaming to River Song.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import logging
from typing import Optional

from core.config import config
from core.constants import VortexState
from audio.microphone import Microphone, MicrophoneError
from audio.speaker import Speaker
from audio.wake_word import WakeWordDetector

logger = logging.getLogger(__name__)


class AudioManager:
    """
    Coordinates all audio I/O for River Vortex.

    Voice command flow (privacy-safe):
        Mic (local) → Porcupine (local) → chime → stream to River Song → TTS response → Speaker

    Audio is NEVER sent to River Song until the wake word is confirmed locally.

    Args:
        ha_client: Optional Home Assistant client reference, passed to
                   command handlers that may need to trigger HA actions.
    """

    def __init__(self, ha_client=None) -> None:
        """Initialize AudioManager with all audio subsystem components."""
        self._ha_client = ha_client
        self._microphone = Microphone()
        self._speaker = Speaker()
        self._wake_word_detector: Optional[WakeWordDetector] = None
        self._running: bool = False
        self._state: VortexState = VortexState.IDLE

    async def start(self) -> None:
        """
        Start all audio subsystems.

        Opens the microphone, starts the speaker playback thread, and
        initializes the wake word detector.
        """
        logger.info("Starting AudioManager...")
        self._running = True

        try:
            self._microphone.open()
        except MicrophoneError as exc:
            logger.error("Microphone failed to open: %s — audio input disabled.", exc)

        self._speaker.start()

        self._wake_word_detector = WakeWordDetector(
            on_wake_word=self._on_wake_word_detected,
        )
        self._wake_word_detector.start()

        logger.info("AudioManager started.")

    async def stop(self) -> None:
        """
        Stop all audio subsystems gracefully.

        Stops wake word detection, closes the microphone, and stops the speaker.
        """
        logger.info("Stopping AudioManager...")
        self._running = False

        if self._wake_word_detector:
            self._wake_word_detector.stop()

        self._microphone.close()
        self._speaker.stop()

        logger.info("AudioManager stopped.")

    def set_volume(self, level: int) -> None:
        """
        Set speaker volume.

        Args:
            level: Volume 0–100.
        """
        self._speaker.set_volume(level)

    def mute_microphone(self) -> None:
        """Mute the microphone (software mute)."""
        self._microphone.mute()

    def unmute_microphone(self) -> None:
        """Unmute the microphone."""
        self._microphone.unmute()

    # ─────────────────────────────────────────────────────────────────────────
    # Wake Word → Command Flow
    # ─────────────────────────────────────────────────────────────────────────

    def _on_wake_word_detected(self) -> None:
        """
        Callback invoked by WakeWordDetector when the wake word is confirmed.

        Runs on the detector thread. Schedules the async command capture
        coroutine on the main event loop.

        Privacy note: This callback receives NO audio data. The wake word
        detector only signals detection — it does not pass audio frames.
        """
        logger.info("Wake word detected — initiating command capture.")
        self._speaker.play_chime("wake")

        # Schedule the async command flow on the running event loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(self._capture_and_process_command(), loop)
            else:
                logger.warning("No running event loop — cannot schedule command capture.")
        except RuntimeError as exc:
            logger.error("Failed to schedule command capture: %s", exc)

    async def _capture_and_process_command(self) -> None:
        """
        Capture a voice command from the microphone and send it to River Song.

        This is the ONLY place audio is streamed to River Song. Audio capture
        begins only after local wake word confirmation.

        Flow:
          1. Collect PCM chunks from microphone until silence
          2. POST audio to River Song /api/vortex/v1/command
          3. Receive TTS audio response
          4. Play response through speaker
        """
        if not self._running:
            return

        self._state = VortexState.LISTENING
        logger.info("Capturing voice command...")

        audio_chunks = []
        try:
            for chunk in self._microphone.stream_until_silence():
                audio_chunks.append(chunk)
        except MicrophoneError as exc:
            logger.error("Microphone error during command capture: %s", exc)
            self._speaker.play_chime("error")
            self._state = VortexState.IDLE
            return

        if not audio_chunks:
            logger.warning("No audio captured — ignoring.")
            self._state = VortexState.IDLE
            return

        audio_data = b"".join(audio_chunks)
        logger.info("Command captured: %d bytes. Sending to River Song.", len(audio_data))

        self._state = VortexState.PROCESSING
        try:
            from connectivity.api_client import APIClient
            client = APIClient()
            response_audio = await client.send_voice_command(audio_data)

            if response_audio:
                self._state = VortexState.RESPONDING
                self._speaker.play(response_audio, interrupt=True)
                self._speaker.play_chime("done")
            else:
                logger.warning("River Song returned no audio response.")
                self._speaker.play_chime("error")

        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to process command with River Song: %s", exc)
            self._speaker.play_chime("error")
        finally:
            self._state = VortexState.IDLE
