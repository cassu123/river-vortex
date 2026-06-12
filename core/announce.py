"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/announce.py
Purpose:     Multi-room announcements ("broadcast" / "radio" / "Drop In"
             messages). Plays a message (and optional pre-rendered TTS audio)
             through this unit's speaker, ducking any currently-playing media
             first and restoring it afterward. River Song is responsible for
             fanning an announcement out to every paired Vortex unit
             (phone → house, or room → all rooms) — Vortex's job is just to
             play the announcement locally and show it on-screen.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-12
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from core.constants import (
    ANNOUNCEMENT_DEFAULT_DURATION_SECONDS,
    ANNOUNCEMENT_DUCK_VOLUME_LEVEL,
    ANNOUNCEMENT_MAX_DURATION_SECONDS,
)
from core.ws_hub import ws_hub

logger = logging.getLogger(__name__)


def _estimate_duration(message: str) -> float:
    """Roughly estimate TTS playback duration from word count (~2.5 words/sec)."""
    words = len(message.split())
    estimate = max(ANNOUNCEMENT_DEFAULT_DURATION_SECONDS, words / 2.5 + 1.5)
    return min(estimate, ANNOUNCEMENT_MAX_DURATION_SECONDS)


class AnnouncementSession:
    """
    Plays "Drop In" / broadcast announcements on this unit, ducking
    background media for the duration.

    Usage:
        session = AnnouncementSession(device_control=dc, audio_manager=am)
        await session.announce("Dinner's ready!", source="Kitchen Vortex")
    """

    def __init__(
        self,
        device_control: Optional[Any] = None,
        audio_manager: Optional[Any] = None,
    ) -> None:
        """
        Initialize AnnouncementSession.

        Args:
            device_control: Optional home_assistant.device_control.DeviceControl
                             used to duck/restore media player volume. If None
                             (e.g., no Home Assistant configured), ducking is skipped.
            audio_manager:  Optional audio.audio_manager.AudioManager used to
                             play a chime when an announcement arrives. If None,
                             no chime is played.
        """
        self._device_control = device_control
        self._audio_manager = audio_manager
        self._ducked_players: Dict[str, float] = {}
        self._restore_task: Optional[asyncio.Task] = None

    async def announce(
        self,
        message: str,
        source: Optional[str] = None,
        priority: str = "normal",
        audio_url: Optional[str] = None,
        duration_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Play an announcement, ducking background media for its duration.

        Args:
            message:          The announcement text to display (and speak,
                               if River Song renders TTS).
            source:           Optional human-readable origin, e.g. "Kitchen
                               Vortex" or "Chris's Phone".
            priority:         "normal" or "urgent".
            audio_url:        Optional URL to pre-rendered TTS audio for the
                               frontend/speaker to play.
            duration_seconds: Optional explicit playback/ducking duration. If
                               omitted, estimated from the message length.

        Returns:
            The broadcast announcement dict (id, message, source, priority,
            audio_url, timestamp).
        """
        if self._restore_task and not self._restore_task.done():
            self._restore_task.cancel()
        if not self._ducked_players:
            await self._duck_media()

        announcement = {
            "id": str(uuid.uuid4()),
            "message": message,
            "source": source,
            "priority": priority,
            "audio_url": audio_url,
            "timestamp": datetime.now().isoformat(),
        }

        await ws_hub.broadcast({"type": "announcement", "announcement": announcement})

        if self._audio_manager:
            try:
                self._audio_manager.play_chime("intercom")
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Failed to play announcement chime: %s", exc)

        delay = duration_seconds if duration_seconds is not None else _estimate_duration(message)
        self._restore_task = asyncio.create_task(self._restore_after(delay), name="announcement-restore")

        logger.info("Announcement from '%s': %s", source or "unknown", message[:80])
        return announcement

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    async def _restore_after(self, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await self._restore_media()
        except asyncio.CancelledError:
            pass

    async def _duck_media(self) -> None:
        """Lower the volume of any currently-playing media players, remembering their levels."""
        self._ducked_players = {}
        if not self._device_control:
            return

        try:
            players = await self._device_control.get_all_media_players()
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Could not query media players for ducking: %s", exc)
            return

        for player in players:
            if player.get("state") != "playing":
                continue
            entity_id = player.get("entity_id")
            volume = player.get("attributes", {}).get("volume_level")
            if entity_id is None or volume is None:
                continue
            self._ducked_players[entity_id] = volume
            await self._device_control.set_media_volume(entity_id, ANNOUNCEMENT_DUCK_VOLUME_LEVEL)

        if self._ducked_players:
            logger.info("Ducked %d media player(s) for announcement.", len(self._ducked_players))

    async def _restore_media(self) -> None:
        """Restore the volume of any media players ducked by _duck_media()."""
        if not self._device_control or not self._ducked_players:
            self._ducked_players = {}
            return

        for entity_id, volume in self._ducked_players.items():
            await self._device_control.set_media_volume(entity_id, volume)

        logger.info("Restored volume for %d media player(s).", len(self._ducked_players))
        self._ducked_players = {}
