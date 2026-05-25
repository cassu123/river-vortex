"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        connectivity/wifi_manager.py
Purpose:     WiFi connectivity monitoring and management. Periodically checks
             network reachability, triggers cellular fallback when WiFi is lost,
             and notifies other subsystems of connectivity state changes.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import logging
from typing import Callable, List, Optional

from core.constants import (
    CONNECTIVITY_HEALTH_ENDPOINT,
    CONNECTIVITY_TIMEOUT_SECONDS,
    ConnectivityState,
    WIFI_CHECK_INTERVAL_SECONDS,
    WIFI_RECONNECT_ATTEMPTS,
    WIFI_RECONNECT_DELAY_SECONDS,
)

logger = logging.getLogger(__name__)


class WiFiManager:
    """
    Monitors WiFi connectivity and manages fallback to cellular.

    Runs a background async task that periodically checks reachability.
    Notifies registered listeners when connectivity state changes.

    Cellular fallback is triggered automatically when WiFi is lost and
    cellular is enabled in the unit profile.
    """

    def __init__(self) -> None:
        """Initialize WiFiManager."""
        self._state: ConnectivityState = ConnectivityState.WIFI_DISCONNECTED
        self._monitor_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._state_change_listeners: List[Callable[[ConnectivityState], None]] = []

    async def start(self) -> None:
        """Start the connectivity monitoring background task."""
        self._running = True
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(), name="wifi-monitor"
        )
        logger.info("WiFiManager started.")

    async def stop(self) -> None:
        """Stop the connectivity monitor."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("WiFiManager stopped.")

    def add_state_listener(self, listener: Callable[[ConnectivityState], None]) -> None:
        """
        Register a callback for connectivity state changes.

        Args:
            listener: Callable that receives the new ConnectivityState.
        """
        self._state_change_listeners.append(listener)

    @property
    def state(self) -> ConnectivityState:
        """Return the current connectivity state."""
        return self._state

    async def is_reachable(self) -> bool:
        """
        Check if the internet is currently reachable.

        Returns:
            True if the health endpoint responds within the timeout.
        """
        try:
            import httpx
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(CONNECTIVITY_TIMEOUT_SECONDS)
            ) as client:
                response = await client.get(CONNECTIVITY_HEALTH_ENDPOINT)
                return response.status_code < 500
        except Exception:
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    async def _monitor_loop(self) -> None:
        """
        Periodically check connectivity and update state.

        Runs every WIFI_CHECK_INTERVAL_SECONDS seconds.
        """
        while self._running:
            reachable = await self.is_reachable()
            new_state = (
                ConnectivityState.WIFI_CONNECTED
                if reachable
                else ConnectivityState.WIFI_DISCONNECTED
            )
            if new_state != self._state:
                logger.info(
                    "Connectivity state changed: %s → %s",
                    self._state.name,
                    new_state.name,
                )
                self._state = new_state
                self._notify_listeners(new_state)

            await asyncio.sleep(WIFI_CHECK_INTERVAL_SECONDS)

    def _notify_listeners(self, state: ConnectivityState) -> None:
        """
        Notify all registered listeners of a state change.

        Args:
            state: The new ConnectivityState.
        """
        for listener in self._state_change_listeners:
            try:
                listener(state)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Connectivity listener error: %s", exc)
