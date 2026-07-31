"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/voice.py
Purpose:     Spoken output for a Vortex unit.

             Vortex has no speech engine of its own — River Song runs Piper and
             owns River's actual voice. But a unit must still be able to speak
             when River Song is unreachable, otherwise a screenless unit goes
             completely silent the moment the server reboots.

             So speech is attempted in three tiers, best first:
               1. River Song TTS  — River's real voice, needs the server
               2. local espeak-ng — robotic but works fully offline
               3. chime only      — at least something audible happens

             Callers just say speak("your timer is done") and never think
             about which tier answered.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import logging
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

# Cap on how long the local fallback may take before we give up and chime.
_ESPEAK_TIMEOUT_SECONDS = 10


class VoiceOutput:
    """
    Turns text into audible speech on this unit.

    Args:
        audio_manager: The AudioManager owning the speaker. May be None on a
                       unit with audio disabled, in which case every speak()
                       call is a logged no-op rather than an error.
    """

    def __init__(self, audio_manager=None) -> None:
        """Initialize with an optional AudioManager."""
        self._audio_manager = audio_manager
        # Resolved once — shutil.which on every timer would be wasteful.
        self._espeak_path: Optional[str] = shutil.which("espeak-ng") or shutil.which("espeak")
        if not self._espeak_path:
            logger.info(
                "espeak-ng not installed — offline speech unavailable. "
                "Install it so units can still talk when River Song is down: "
                "sudo apt install espeak-ng"
            )

    def set_audio_manager(self, audio_manager) -> None:
        """Attach the AudioManager once audio has started."""
        self._audio_manager = audio_manager

    async def speak(self, text: str, interrupt: bool = False) -> bool:
        """
        Say something out loud, using the best tier available.

        Args:
            text:      What to say. Empty strings are ignored.
            interrupt: Cut off whatever is currently playing.

        Returns:
            True if audio was produced by any tier, False if the unit stayed
            silent (no speaker, or every tier failed).
        """
        if not text or not text.strip():
            return False

        if self._audio_manager is None:
            logger.debug("No audio manager — cannot speak: %s", text[:60])
            return False

        # Tier 1 — River Song's real voice.
        audio = await self._tts_from_river_song(text)
        if audio:
            self._audio_manager.speaker.play(audio, interrupt=interrupt)
            return True

        # Tier 2 — local, offline, robotic but intelligible.
        audio = await self._tts_local(text)
        if audio:
            logger.debug("Spoke via local espeak fallback: %s", text[:60])
            self._audio_manager.speaker.play(audio, interrupt=interrupt)
            return True

        # Tier 3 — at minimum make a noise so the user knows something happened.
        logger.warning("No speech available; falling back to chime for: %s", text[:60])
        try:
            self._audio_manager.play_chime("done")
            return True
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Even the chime failed: %s", exc)
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Private — tiers
    # ─────────────────────────────────────────────────────────────────────────

    async def _tts_from_river_song(self, text: str) -> Optional[bytes]:
        """
        Ask River Song to render the text in River's voice.

        Returns:
            WAV bytes, or None if River Song is unreachable or has no TTS
            endpoint configured yet.
        """
        try:
            from connectivity.api_client import APIClient
            client = APIClient()
            speak_fn = getattr(client, "synthesize_speech", None)
            if speak_fn is None:
                # The server-side TTS endpoint is not wired up yet. Not an
                # error — just means we go straight to the local fallback.
                return None
            return await speak_fn(text)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("River Song TTS unavailable (%s) — falling back.", exc)
            return None

    async def _tts_local(self, text: str) -> Optional[bytes]:
        """
        Render speech locally with espeak-ng.

        Runs in a worker thread — espeak is a blocking subprocess and would
        otherwise stall the event loop, freezing the UI and the watchdog.

        Returns:
            WAV bytes, or None if espeak is missing or failed.
        """
        if not self._espeak_path:
            return None

        def _render() -> Optional[bytes]:
            try:
                result = subprocess.run(
                    [self._espeak_path, "--stdout", text],
                    capture_output=True,
                    timeout=_ESPEAK_TIMEOUT_SECONDS,
                    check=False,
                )
                if result.returncode != 0 or not result.stdout:
                    logger.debug("espeak returned %d", result.returncode)
                    return None
                return result.stdout
            except (subprocess.TimeoutExpired, OSError) as exc:
                logger.debug("espeak failed: %s", exc)
                return None

        return await asyncio.to_thread(_render)


# Module-level singleton — import this, mirroring the ws_hub pattern.
voice = VoiceOutput()
