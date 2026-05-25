"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        connectivity/cellular.py
Purpose:     4G LTE cellular fallback connectivity management. Activates when
             WiFi is unavailable. Interfaces with ModemManager or a USB LTE
             dongle via AT commands or NetworkManager. Provides the same
             connectivity interface as WiFiManager for transparent fallback.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import logging
import subprocess
from typing import Optional

from core.config import config
from core.constants import (
    CELLULAR_APN_DEFAULT,
    CELLULAR_CHECK_INTERVAL_SECONDS,
    ConnectivityState,
)

logger = logging.getLogger(__name__)


class CellularManager:
    """
    Manages 4G LTE cellular fallback connectivity.

    Activates automatically when WiFiManager reports disconnection and
    cellular is enabled in the unit profile. Uses ModemManager (mmcli)
    or NetworkManager (nmcli) depending on what is available on the host.

    This is a fallback path only — WiFi is always preferred.
    """

    def __init__(self) -> None:
        """Initialize CellularManager."""
        self._enabled: bool = config.get("cellular_enabled", False)
        self._apn: str = config.get("cellular_apn", CELLULAR_APN_DEFAULT)
        self._active: bool = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._running: bool = False

    async def start(self) -> None:
        """
        Start the cellular manager.

        If cellular is disabled in the profile, this is a no-op.
        """
        if not self._enabled:
            logger.info("Cellular fallback is disabled in unit profile.")
            return

        self._running = True
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(), name="cellular-monitor"
        )
        logger.info("CellularManager started (APN: %s).", self._apn or "default")

    async def stop(self) -> None:
        """Stop the cellular manager and deactivate the connection if active."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        if self._active:
            await self.deactivate()
        logger.info("CellularManager stopped.")

    async def activate(self) -> bool:
        """
        Activate the cellular data connection.

        Attempts to bring up the LTE interface via nmcli or mmcli.

        Returns:
            True if the connection was activated successfully.
        """
        if self._active:
            logger.debug("Cellular already active.")
            return True

        logger.info("Activating cellular fallback (APN: %s)...", self._apn)
        try:
            # Try NetworkManager first (most common on Pi OS)
            result = subprocess.run(
                ["nmcli", "connection", "up", "cellular"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                self._active = True
                logger.info("Cellular connection activated via nmcli.")
                return True
            else:
                logger.warning("nmcli cellular activation failed: %s", result.stderr.strip())
        except FileNotFoundError:
            logger.debug("nmcli not found — trying mmcli.")
        except subprocess.TimeoutExpired:
            logger.error("Cellular activation timed out.")
            return False

        # Fallback: try ModemManager
        try:
            result = subprocess.run(
                ["mmcli", "-m", "0", "--simple-connect", f"apn={self._apn}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                self._active = True
                logger.info("Cellular connection activated via mmcli.")
                return True
            else:
                logger.error("mmcli cellular activation failed: %s", result.stderr.strip())
        except FileNotFoundError:
            logger.error("Neither nmcli nor mmcli found. Cannot activate cellular.")
        except subprocess.TimeoutExpired:
            logger.error("mmcli cellular activation timed out.")

        return False

    async def deactivate(self) -> None:
        """Deactivate the cellular data connection."""
        if not self._active:
            return
        try:
            subprocess.run(
                ["nmcli", "connection", "down", "cellular"],
                capture_output=True,
                timeout=10,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Error deactivating cellular: %s", exc)
        self._active = False
        logger.info("Cellular connection deactivated.")

    @property
    def is_active(self) -> bool:
        """Return True if the cellular connection is currently active."""
        return self._active

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    async def _monitor_loop(self) -> None:
        """
        Periodically verify the cellular connection is still alive.

        If the connection drops, attempt to reconnect.
        """
        while self._running:
            if self._active:
                alive = await self._ping_check()
                if not alive:
                    logger.warning("Cellular connection lost — attempting reconnect.")
                    self._active = False
                    await self.activate()
            await asyncio.sleep(CELLULAR_CHECK_INTERVAL_SECONDS)

    async def _ping_check(self) -> bool:
        """
        Check if the cellular connection has internet access.

        Returns:
            True if a ping to 1.1.1.1 succeeds.
        """
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "3", "1.1.1.1"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False
