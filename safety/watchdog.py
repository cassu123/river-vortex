"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        safety/watchdog.py
Purpose:     System watchdog that monitors all River Vortex subsystems for
             health and responsiveness. Detects crashed or hung subsystems
             and attempts automatic restart within configured limits.
             Reports persistent failures to telemetry.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Dict, Optional

from core.constants import (
    WATCHDOG_HEARTBEAT_INTERVAL_SECONDS,
    WATCHDOG_MAX_RESTARTS,
    WATCHDOG_RESTART_DELAY_SECONDS,
)

logger = logging.getLogger(__name__)


class Watchdog:
    """
    Monitors River Vortex subsystems and restarts failed components.

    Each subsystem is expected to expose an `is_healthy()` method.
    If a subsystem fails the health check, the watchdog calls its
    `stop()` and `start()` methods to attempt recovery.

    Restart attempts are counted per subsystem per hour. If a subsystem
    exceeds WATCHDOG_MAX_RESTARTS, it is marked as failed and left offline
    to prevent restart loops.

    Usage:
        watchdog = Watchdog(subsystems={"audio": audio_manager, ...})
        await watchdog.start()
    """

    def __init__(self, subsystems: Dict[str, Any]) -> None:
        """
        Initialize the Watchdog.

        Args:
            subsystems: Dict mapping subsystem name → manager instance.
                        Each instance should have is_healthy(), start(), stop().
        """
        self._subsystems = {k: v for k, v in subsystems.items() if v is not None}
        self._restart_counts: Dict[str, int] = defaultdict(int)
        self._restart_window_start: Dict[str, float] = {}
        self._failed_subsystems: set = set()
        self._monitor_task: Optional[asyncio.Task] = None
        self._running: bool = False

    async def start(self) -> None:
        """Start the watchdog monitoring loop."""
        self._running = True
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(), name="watchdog-monitor"
        )
        logger.info(
            "Watchdog started. Monitoring %d subsystems: %s",
            len(self._subsystems),
            ", ".join(self._subsystems.keys()),
        )

    async def stop(self) -> None:
        """Stop the watchdog."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Watchdog stopped.")

    def get_status(self) -> Dict[str, str]:
        """
        Return the health status of all monitored subsystems.

        Returns:
            Dict mapping subsystem name → status string ("ok", "failed", "unknown").
        """
        status = {}
        for name, subsystem in self._subsystems.items():
            if name in self._failed_subsystems:
                status[name] = "failed"
            elif hasattr(subsystem, "is_healthy"):
                try:
                    status[name] = "ok" if subsystem.is_healthy() else "degraded"
                except Exception:
                    status[name] = "unknown"
            else:
                status[name] = "unknown"
        return status

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    async def _monitor_loop(self) -> None:
        """
        Periodically check all subsystems and restart failed ones.

        Runs every WATCHDOG_HEARTBEAT_INTERVAL_SECONDS seconds.
        """
        while self._running:
            for name, subsystem in self._subsystems.items():
                if name in self._failed_subsystems:
                    continue
                await self._check_subsystem(name, subsystem)
            await asyncio.sleep(WATCHDOG_HEARTBEAT_INTERVAL_SECONDS)

    async def _check_subsystem(self, name: str, subsystem: Any) -> None:
        """
        Check a single subsystem's health and restart if needed.

        Args:
            name:      The subsystem name.
            subsystem: The subsystem manager instance.
        """
        is_healthy_fn = getattr(subsystem, "is_healthy", None)
        if not is_healthy_fn:
            return  # Subsystem doesn't support health checks

        try:
            healthy = is_healthy_fn()
        except Exception as exc:
            logger.warning("Health check for '%s' raised exception: %s", name, exc)
            healthy = False

        if not healthy:
            logger.warning("Subsystem '%s' is unhealthy — attempting restart.", name)
            await self._restart_subsystem(name, subsystem)

    async def _restart_subsystem(self, name: str, subsystem: Any) -> None:
        """
        Attempt to restart a failed subsystem.

        Enforces the restart rate limit. Marks the subsystem as permanently
        failed if the limit is exceeded.

        Args:
            name:      The subsystem name.
            subsystem: The subsystem manager instance.
        """
        # Reset restart counter if the window has expired (1 hour)
        now = time.monotonic()
        window_start = self._restart_window_start.get(name, now)
        if now - window_start > 3600:
            self._restart_counts[name] = 0
            self._restart_window_start[name] = now

        if self._restart_counts[name] >= WATCHDOG_MAX_RESTARTS:
            logger.error(
                "Subsystem '%s' has exceeded max restarts (%d/hr). Marking as failed.",
                name,
                WATCHDOG_MAX_RESTARTS,
            )
            self._failed_subsystems.add(name)
            return

        self._restart_counts[name] += 1
        logger.info(
            "Restarting '%s' (attempt %d/%d)...",
            name,
            self._restart_counts[name],
            WATCHDOG_MAX_RESTARTS,
        )

        await asyncio.sleep(WATCHDOG_RESTART_DELAY_SECONDS)

        try:
            stop_fn = getattr(subsystem, "stop", None)
            if stop_fn:
                if asyncio.iscoroutinefunction(stop_fn):
                    await stop_fn()
                else:
                    stop_fn()
        except Exception as exc:
            logger.error("Error stopping '%s' during restart: %s", name, exc)

        try:
            start_fn = getattr(subsystem, "start", None)
            if start_fn:
                if asyncio.iscoroutinefunction(start_fn):
                    await start_fn()
                else:
                    start_fn()
            logger.info("Subsystem '%s' restarted successfully.", name)
        except Exception as exc:
            logger.error("Failed to restart '%s': %s", name, exc)
