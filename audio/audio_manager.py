"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        audio/audio_manager.py
Purpose:     Top-level audio subsystem coordinator. Owns the wake word detector,
             microphone, and speaker. Orchestrates the full voice command flow:
               1. Wake word detected locally (openWakeWord — no cloud)
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
from core.ws_hub import ws_hub
from audio.microphone import Microphone, MicrophoneError
from audio.speaker import Speaker
from audio.wake_word import WakeWordDetector

logger = logging.getLogger(__name__)

#: What River says when she cannot be reached. Spoken locally, so a unit that
#: has lost the server still answers with words rather than a bare error tone —
#: a beep tells you something went wrong but not what, and on a screenless Mini
#: it is the only thing you get.
UNREACHABLE_PHRASE = "I can't reach River Song right now."

#: When the microphone itself failed, rather than the network.
MIC_FAILURE_PHRASE = "I'm having trouble with my microphone."

#: When River Song took the command and then went quiet. Says less than the
#: unreachable phrase because the network is plainly fine — something further
#: in failed, and guessing at what would be worse than admitting it.
NO_REPLY_PHRASE = "Sorry, I didn't get an answer to that."

#: How long to wait for River Song to start answering before giving up on her.
#: Generous: transcription plus intent routing plus speech synthesis is a real
#: amount of work, and cutting her off mid-thought is worse than a pause.
REPLY_TIMEOUT_SECONDS = 20.0


class AudioManager:
    """
    Coordinates all audio I/O for River Vortex.

    Voice command flow (privacy-safe):
        Mic (local) → openWakeWord (local) → chime → uplink to River Song → TTS → Speaker

    Audio is NEVER sent to River Song until the wake word is confirmed locally.

    Args:
        ha_client: Optional Home Assistant client reference, passed to
                   command handlers that may need to trigger HA actions.
    """

    def __init__(self, ha_client=None, privacy_manager=None) -> None:
        """
        Args:
            ha_client:       Optional Home Assistant client reference.
            privacy_manager: The mute authority. Passed in at construction
                rather than attached later so there is no window in which the
                microphone is open and the mute is not yet being enforced.
        """
        self._ha_client = ha_client
        self._privacy = privacy_manager
        self._microphone = Microphone()
        if privacy_manager is not None:
            self._microphone.set_privacy_manager(privacy_manager)
        self._speaker = Speaker()
        self._wake_word_detector: Optional[WakeWordDetector] = None
        self._running: bool = False
        # Set directly only here, before there is a loop to broadcast on.
        # Everywhere else goes through _set_state so the orb cannot fall out
        # of sync with what the unit is actually doing.
        self._state: VortexState = VortexState.IDLE
        # Captured in start(). The wake word callback fires on the detector
        # thread, which has no event loop of its own — it needs an explicit
        # reference to the main loop to schedule work onto.
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self) -> None:
        """
        Start all audio subsystems.

        Opens the microphone, starts the speaker playback thread, and
        initializes the wake word detector.
        """
        logger.info("Starting AudioManager...")
        self._running = True

        # start() runs on the main event loop; capture it now so the wake word
        # detector thread can schedule the command flow back onto it.
        self._loop = asyncio.get_running_loop()

        try:
            self._microphone.open()
        except MicrophoneError as exc:
            logger.error("Microphone failed to open: %s — audio input disabled.", exc)

        self._speaker.start()

        self._wake_word_detector = WakeWordDetector(
            on_wake_word=self._on_wake_word_detected,
            privacy_manager=self._privacy,
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

    def play_chime(self, chime_type: str = "done") -> None:
        """
        Play a short system chime through the speaker.

        Used by other subsystems (e.g., TimerManager) to announce events
        without going through the full voice command pipeline.

        Args:
            chime_type: One of 'wake', 'done', 'error', 'intercom'.
        """
        self._speaker.play_chime(chime_type)

    def mute_microphone(self) -> None:
        """Mute the microphone (software mute)."""
        self._microphone.mute()

    def unmute_microphone(self) -> None:
        """Unmute the microphone."""
        self._microphone.unmute()

    @property
    def wake_word_detector(self) -> Optional[WakeWordDetector]:
        """
        The wake word detector — exposed so the uplink can retune it when
        River Song reports the household has chosen a different phrase.
        """
        return self._wake_word_detector

    @property
    def microphone(self) -> Microphone:
        """The underlying Microphone instance — used by IntercomManager for call audio."""
        return self._microphone

    @property
    def speaker(self) -> Speaker:
        """The underlying Speaker instance — used by IntercomManager for call audio."""
        return self._speaker

    # ─────────────────────────────────────────────────────────────────────────
    # Presence — telling the screen what this unit is doing
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def state(self) -> VortexState:
        """What the unit is currently doing."""
        return self._state

    async def _set_state(self, state: VortexState) -> None:
        """
        Change state and tell every connected display, in one call.

        This exists as a single method rather than a bare assignment because
        the two used to be separate and the second half was simply never
        written: AudioManager tracked LISTENING → PROCESSING → RESPONDING
        perfectly and told nobody, so the presence orb sat on idle forever
        while the unit was plainly busy. Binding them together means a future
        state cannot be added without the screen learning about it.
        """
        self._state = state
        await self._publish_presence(state)

    async def _publish_presence(self, state: VortexState) -> None:
        """
        Broadcast the presence state to the frontend.

        The frontend maps VortexState names itself (see toPresenceState in
        presenceContract.js), so the enum name is sent as-is rather than
        translated here — one mapping table, on the side that renders it.

        A broadcast failure must never break the voice path: losing the orb
        is cosmetic, losing the ability to answer is not.
        """
        try:
            await ws_hub.broadcast({
                "type": "presence",
                "data": {"state": state.name},
            })
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Presence broadcast failed (%s) — continuing.", exc)

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

        # Schedule the async command flow onto the main event loop.
        #
        # This must use the loop captured in start(), NOT asyncio.get_event_loop().
        # This callback runs on the wake word detector thread, and since Python
        # 3.10 get_event_loop() raises RuntimeError in a thread that has no loop
        # of its own — which silently killed the entire voice path.
        loop = self._loop
        if loop is None or loop.is_closed():
            logger.error("AudioManager has no event loop — cannot capture command.")
            return

        try:
            asyncio.run_coroutine_threadsafe(self._capture_and_process_command(), loop)
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

        await self._set_state(VortexState.LISTENING)
        logger.info("Capturing voice command...")

        # stream_until_silence() is a BLOCKING generator over PyAudio reads —
        # it can run for up to MAX_COMMAND_DURATION_SECONDS. Running it inline
        # would stall the event loop for that whole time, freezing the UI
        # WebSocket, the watchdog, and the HA connection. Collect it on a
        # worker thread instead.
        def _collect() -> list:
            return list(self._microphone.stream_until_silence())

        try:
            audio_chunks = await asyncio.to_thread(_collect)
        except MicrophoneError as exc:
            logger.error("Microphone error during command capture: %s", exc)
            await self._say_locally(MIC_FAILURE_PHRASE)
            await self._set_state(VortexState.IDLE)
            return

        if not audio_chunks:
            # Woken by mistake, or the user said nothing. Saying "I didn't
            # catch that" to an empty room is worse than staying quiet.
            logger.warning("No audio captured — ignoring.")
            await self._set_state(VortexState.IDLE)
            return

        audio_data = b"".join(audio_chunks)
        logger.info("Command captured: %d bytes. Sending to River Song.", len(audio_data))

        await self._set_state(VortexState.PROCESSING)
        try:
            sent = await self._send_to_river_song(audio_data)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to send command to River Song: %s", exc)
            sent = False

        if not sent:
            await self._set_state(VortexState.RESPONDING)
            await self._say_locally(UNREACHABLE_PHRASE)
            await self._set_state(VortexState.IDLE)
            return

        # Deliberately NOT setting IDLE here. The answer arrives asynchronously
        # as `presence` and `audio` frames pushed back over the uplink, and
        # River Song owns the orb from this point: it knows when it is
        # thinking and when it starts speaking, and it streams the amplitude
        # that makes the orb track her voice. Forcing IDLE now would blank the
        # orb a fraction of a second before she answers.
        await self._await_reply()

    async def _await_reply(self) -> None:
        """
        Make sure a silent server does not leave the orb spinning forever.

        Handing the utterance off means River Song owns the presence state
        from here, which is right while she is answering — and a trap if she
        never does. A transcription that fails, an intent that throws, a
        server restarted mid-sentence: any of those leave the unit sat in
        PROCESSING with a pulsing orb and no explanation, and on a wall panel
        there is nothing the user can do about it.

        So: wait, and if nothing came back, say so out loud and stand down.
        """
        from connectivity.vortex_link import vortex_link

        before = vortex_link.last_reply_at
        await asyncio.sleep(REPLY_TIMEOUT_SECONDS)

        if vortex_link.last_reply_at > before:
            return  # She answered. The server has driven the orb since.

        logger.warning("River Song accepted the command but never replied.")
        await self._set_state(VortexState.RESPONDING)
        await self._say_locally(NO_REPLY_PHRASE)
        await self._set_state(VortexState.IDLE)

    async def _send_to_river_song(self, audio_data: bytes) -> bool:
        """
        Hand a captured command to River Song.

        Sent over the uplink WebSocket as `audio_chunk` frames rather than
        POSTed: the REST endpoint this used to call, /api/vortex/v1/command,
        does not exist on the server and never has, so every spoken command
        got a 404 and the user heard an error tone. Audio belongs on the
        socket the unit already holds — one auth path, and River Song can push
        her reply and the orb's envelope back down the same pipe.

        Returns:
            True if the audio reached River Song.
        """
        from connectivity.vortex_link import vortex_link

        if not vortex_link.connected:
            logger.warning("Command not sent — no uplink to River Song.")
            return False
        return await vortex_link.send_utterance(audio_data)

    async def _say_locally(self, phrase: str) -> None:
        """
        Say something without going back to River Song.

        Used on the failure paths, where the server has just proven itself
        unreachable — asking it to render the apology would stall for the
        connect timeout and then fail anyway, with the user stood there
        waiting. voice.speak still falls through espeak-ng to a chime, so a
        unit with no offline speech installed is no worse off than before.
        """
        try:
            from core.voice import voice
            await voice.speak(phrase, interrupt=True, prefer_local=True)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Local speech failed (%s) — falling back to chime.", exc)
            try:
                self._speaker.play_chime("error")
            except Exception:  # pylint: disable=broad-except
                pass
