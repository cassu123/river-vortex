"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        display/ambient_mode.py
Purpose:     Ambient display mode controller. Manages the always-on clock,
             weather data fetching, and notification overlay for the ambient
             screen. Runs continuously when the device is idle. Provides
             data to the React frontend Ambient page via the backend API.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from core.config import config
from core.constants import RIVER_SONG_WEATHER_ENDPOINT
from core.constants import (
    AMBIENT_CLOCK_UPDATE_INTERVAL,
    AMBIENT_WEATHER_UPDATE_INTERVAL,
)

logger = logging.getLogger(__name__)


class AmbientMode:
    """
    Manages data for the ambient display mode.

    Provides:
    - Current time (updated every second)
    - Weather data (fetched from River Song API every 10 minutes)
    - Active notifications for overlay display

    The React frontend polls /api/ambient/state or subscribes via WebSocket
    to receive updates from this module.
    """

    def __init__(self) -> None:
        """Initialize AmbientMode."""
        self._running: bool = False
        self._clock_task: Optional[asyncio.Task] = None
        self._weather_task: Optional[asyncio.Task] = None
        self._current_time: str = ""
        self._current_date: str = ""
        self._weather_data: Dict[str, Any] = {}
        self._notifications: list = []

    async def start(self) -> None:
        """Start the ambient mode data update loops."""
        self._running = True
        self._clock_task = asyncio.create_task(
            self._clock_loop(), name="ambient-clock"
        )
        self._weather_task = asyncio.create_task(
            self._weather_loop(), name="ambient-weather"
        )
        logger.info("AmbientMode started.")

    async def stop(self) -> None:
        """Stop all ambient mode update loops."""
        self._running = False
        for task in (self._clock_task, self._weather_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logger.info("AmbientMode stopped.")

    def get_state(self) -> Dict[str, Any]:
        """
        Return the current ambient display state.

        Returns:
            Dict with time, date, weather, and notifications.
        """
        return {
            "time": self._current_time,
            "date": self._current_date,
            "weather": self._weather_data,
            "notifications": self._notifications,
        }

    async def broadcast_state(self) -> None:
        """
        Push the current ambient state to every connected display.

        The frontend has always handled an `ambient_update` message, but
        nothing ever sent one -- so the clock, date and weather it holds never
        reached the screen.
        """
        from core.ws_hub import ws_hub
        await ws_hub.broadcast({"type": "ambient_update", "data": self.get_state()})

    def add_notification(self, notification: Dict[str, Any]) -> None:
        """
        Add a notification to the ambient overlay.

        Args:
            notification: Dict with keys: id, title, message, priority, timestamp.
        """
        self._notifications.append(notification)
        # Keep only the most recent N notifications
        from core.constants import MAX_NOTIFICATIONS_DISPLAYED
        self._notifications = self._notifications[-MAX_NOTIFICATIONS_DISPLAYED:]
        logger.debug("Notification added: %s", notification.get("title", ""))

    def dismiss_notification(self, notification_id: str) -> None:
        """
        Remove a notification by ID.

        Args:
            notification_id: The notification ID to remove.
        """
        self._notifications = [
            n for n in self._notifications if n.get("id") != notification_id
        ]

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    async def _clock_loop(self) -> None:
        """Update the current time string every second."""
        while self._running:
            now = datetime.now()
            time_str = now.strftime("%I:%M %p").lstrip("0")
            changed = time_str != self._current_time
            self._current_time = time_str
            self._current_date = now.strftime("%A, %B %-d")

            # Only broadcast when the displayed minute actually changes --
            # this loop ticks every second and the panel does not need 60
            # identical messages a minute.
            if changed:
                try:
                    await self.broadcast_state()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.debug("Ambient broadcast failed: %s", exc)

            await asyncio.sleep(AMBIENT_CLOCK_UPDATE_INTERVAL)

    async def _weather_loop(self) -> None:
        """Fetch weather data from River Song API every 10 minutes."""
        while self._running:
            try:
                await self._fetch_weather()
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Weather fetch failed: %s", exc)
            await asyncio.sleep(AMBIENT_WEATHER_UPDATE_INTERVAL)

    async def _fetch_weather(self) -> None:
        """
        Fetch current weather from the River Song API.

        River Song aggregates weather data from the configured provider.
        The response is cached in self._weather_data for the frontend.
        """
        try:
            import httpx
            base_url = config.get("river_song_api_url", "http://riversong.local")
            api_key = config.get("river_song_api_key", "")
            unit_id = config.get("unit_id", "vortex-unset")

            headers = {
                "X-Vortex-Unit-ID": unit_id,
                "Authorization": f"Bearer {api_key}" if api_key else "",
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{base_url}{RIVER_SONG_WEATHER_ENDPOINT}",
                    headers=headers,
                )
                if response.status_code == 200:
                    self._weather_data = response.json()
                    logger.debug("Weather updated: %s",
                                 self._weather_data.get("condition", ""))
                    await self.broadcast_state()
                elif response.status_code in (401, 403):
                    # River Song's feeds API authenticates a USER, not a unit.
                    # Until the Vortex channel exposes weather against the unit
                    # token this will keep failing -- say so once, clearly,
                    # rather than logging a bare status code every 10 minutes.
                    logger.warning(
                        "Weather rejected (%d): %s authenticates a user, not a "
                        "unit token. Weather stays unavailable until River Song "
                        "exposes it on the Vortex channel.",
                        response.status_code, RIVER_SONG_WEATHER_ENDPOINT,
                    )
                else:
                    logger.warning("Weather API returned %d.", response.status_code)
        except Exception as exc:
            logger.debug("Weather fetch error: %s", exc)
