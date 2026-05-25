"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        telemetry/collector.py
Purpose:     System telemetry collection. Gathers CPU, memory, temperature,
             disk usage, and subsystem health metrics at regular intervals.
             Stores metrics in a ring buffer and exposes them via the backend
             API. Optionally forwards metrics to River Song for fleet monitoring.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import logging
import time
from collections import deque
from typing import Any, Deque, Dict, Optional

from core.constants import TELEMETRY_FLUSH_INTERVAL_SECONDS, TELEMETRY_MAX_QUEUE_SIZE

logger = logging.getLogger(__name__)


class TelemetryCollector:
    """
    Collects and stores system health metrics for River Vortex.

    Metrics collected:
    - CPU usage percentage
    - Memory usage (used/total MB)
    - CPU temperature (Pi thermal zone)
    - Disk usage percentage
    - Uptime seconds

    Metrics are stored in a fixed-size ring buffer. The most recent
    snapshot is always available via get_latest(). Historical data
    is available via get_history().

    Optionally forwards metrics to River Song for fleet-level monitoring.
    """

    def __init__(self) -> None:
        """Initialize TelemetryCollector."""
        self._history: Deque[Dict[str, Any]] = deque(maxlen=TELEMETRY_MAX_QUEUE_SIZE)
        self._collect_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._start_time: float = time.monotonic()

    async def start(self) -> None:
        """Start the telemetry collection loop."""
        self._running = True
        self._start_time = time.monotonic()
        self._collect_task = asyncio.create_task(
            self._collect_loop(), name="telemetry-collector"
        )
        logger.info("TelemetryCollector started.")

    async def stop(self) -> None:
        """Stop the telemetry collection loop."""
        self._running = False
        if self._collect_task:
            self._collect_task.cancel()
            try:
                await self._collect_task
            except asyncio.CancelledError:
                pass
        logger.info("TelemetryCollector stopped.")

    def get_latest(self) -> Optional[Dict[str, Any]]:
        """
        Return the most recent telemetry snapshot.

        Returns:
            Latest metrics dict, or None if no data has been collected yet.
        """
        return self._history[-1] if self._history else None

    def get_history(self, count: int = 60) -> list:
        """
        Return the last N telemetry snapshots.

        Args:
            count: Number of snapshots to return (most recent first).

        Returns:
            List of metric dicts, newest first.
        """
        snapshots = list(self._history)
        return list(reversed(snapshots[-count:]))

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    async def _collect_loop(self) -> None:
        """Collect metrics at regular intervals."""
        while self._running:
            try:
                snapshot = await self._collect_snapshot()
                self._history.append(snapshot)
                logger.debug(
                    "Telemetry: CPU=%.1f%% MEM=%.0fMB TEMP=%.1f°C",
                    snapshot.get("cpu_percent", 0),
                    snapshot.get("memory_used_mb", 0),
                    snapshot.get("cpu_temp_c", 0),
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Telemetry collection error: %s", exc)
            await asyncio.sleep(TELEMETRY_FLUSH_INTERVAL_SECONDS)

    async def _collect_snapshot(self) -> Dict[str, Any]:
        """
        Collect a single telemetry snapshot.

        Returns:
            Dict with all current system metrics.
        """
        snapshot: Dict[str, Any] = {
            "timestamp": time.time(),
            "uptime_seconds": int(time.monotonic() - self._start_time),
        }

        # CPU and memory via psutil
        try:
            import psutil  # type: ignore
            snapshot["cpu_percent"] = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            snapshot["memory_used_mb"] = round(mem.used / 1024 / 1024, 1)
            snapshot["memory_total_mb"] = round(mem.total / 1024 / 1024, 1)
            snapshot["memory_percent"] = mem.percent
            disk = psutil.disk_usage("/")
            snapshot["disk_used_gb"] = round(disk.used / 1024 / 1024 / 1024, 2)
            snapshot["disk_total_gb"] = round(disk.total / 1024 / 1024 / 1024, 2)
            snapshot["disk_percent"] = disk.percent
        except ImportError:
            logger.debug("psutil not available — CPU/memory metrics skipped.")

        # CPU temperature (Raspberry Pi thermal zone)
        snapshot["cpu_temp_c"] = self._read_cpu_temp()

        return snapshot

    @staticmethod
    def _read_cpu_temp() -> float:
        """
        Read the CPU temperature from the Pi thermal zone sysfs file.

        Returns:
            CPU temperature in Celsius, or 0.0 if unavailable.
        """
        thermal_path = "/sys/class/thermal/thermal_zone0/temp"
        try:
            with open(thermal_path, "r") as fh:
                return round(int(fh.read().strip()) / 1000.0, 1)
        except (FileNotFoundError, ValueError):
            return 0.0
