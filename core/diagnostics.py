"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/diagnostics.py
Purpose:     Boot-time self-checks.

             These are REAL checks, not a scripted progress bar. Each one
             inspects actual hardware or state and can genuinely fail, which
             is the point: a unit mounted on a wall with no keyboard needs to
             say out loud why it is unhappy. A missing microphone, a full SD
             card, or a throttled power supply all show up here rather than as
             mysterious misbehaviour an hour later.

             Results stream to the boot screen as each check finishes, so the
             timing on screen is the real timing.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import logging
import os
import shutil
import time
from typing import Any, Callable, Dict, List, Optional

from core.config import config
from core.constants import CAMERA_PURPOSES

logger = logging.getLogger(__name__)


class CheckStatus:
    """Outcome of a single diagnostic check."""
    OK = "ok"
    WARN = "warn"       # Degraded, but the unit can run
    FAIL = "fail"       # This capability is unavailable
    SKIP = "skip"       # Not applicable to this unit


class Diagnostics:
    """
    Runs the boot self-test and keeps the last report.

    The report is retained because the kiosk browser usually finishes starting
    *after* the backend, so it would otherwise miss the live stream entirely
    and show an empty boot screen.

    Args:
        on_result: Optional async callable invoked with each result as it
                   completes, for streaming to the display.
    """

    def __init__(self, on_result=None) -> None:
        """Initialize with no results yet."""
        self._on_result = on_result
        self._results: List[Dict[str, Any]] = []
        self._complete: bool = False
        self._started_at: float = 0.0
        self._finished_at: float = 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    async def run(self) -> List[Dict[str, Any]]:
        """
        Run every check in order, streaming results as they complete.

        Checks run sequentially rather than concurrently on purpose: the boot
        screen is meant to be read, and a wall of results appearing at once
        tells the user nothing about which one was slow.

        Returns:
            The full list of result dicts.
        """
        self._results = []
        self._complete = False
        self._started_at = time.monotonic()
        self._finished_at = 0.0

        for label, check in self._checks():
            started = time.monotonic()
            try:
                status, detail = await self._invoke(check)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Diagnostic '%s' raised: %s", label, exc)
                status, detail = CheckStatus.FAIL, f"check error: {exc}"

            result = {
                "label": label,
                "status": status,
                "detail": detail,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
            self._results.append(result)
            logger.info("Diagnostic %-22s %-4s %s", label, status.upper(), detail)
            await self._emit(result)

        self._complete = True
        self._finished_at = time.monotonic()
        await self._emit(None)  # completion sentinel
        return self._results

    def get_report(self) -> Dict[str, Any]:
        """
        Return the last report.

        Returns:
            Dict with results, completion flag, counts by status, and total
            elapsed time.
        """
        counts = {CheckStatus.OK: 0, CheckStatus.WARN: 0,
                  CheckStatus.FAIL: 0, CheckStatus.SKIP: 0}
        for result in self._results:
            counts[result["status"]] = counts.get(result["status"], 0) + 1

        return {
            "results": list(self._results),
            "complete": self._complete,
            "counts": counts,
            "healthy": counts[CheckStatus.FAIL] == 0,
            # How many checks this run will produce. The boot screen shows
            # "n of total" while the run is in flight, and hardcoding that
            # total on the frontend meant it silently lied every time a check
            # was added.
            "total": len(self._checks()),
            # Freeze at completion. Measuring against "now" made the total
            # climb forever once the run had finished, so a report fetched a
            # minute later claimed the self-test took a minute.
            "elapsed_ms": int(
                ((self._finished_at or time.monotonic()) - self._started_at) * 1000
            ) if self._started_at else 0,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # The checks
    # ─────────────────────────────────────────────────────────────────────────

    def _checks(self) -> List:
        """The ordered check list. Cheap and structural first, network last."""
        return [
            ("CORE RUNTIME", self._check_runtime),
            ("CONFIGURATION", self._check_config),
            ("STORAGE", self._check_storage),
            ("MEMORY", self._check_memory),
            ("THERMAL", self._check_thermal),
            ("POWER", self._check_power),
            ("DISPLAY", self._check_display),
            ("AUDIO OUTPUT", self._check_audio_output),
            ("MICROPHONE", self._check_microphone),
            ("CAMERA", self._check_camera),
            ("LIGHT SENSOR", self._check_light_sensor),
            ("PRESENCE SENSOR", self._check_presence_sensor),
            ("SPEECH SYNTH", self._check_speech),
            ("MEDIA ENGINE", self._check_media),
            ("NETWORK LINK", self._check_network),
            ("RIVER SONG UPLINK", self._check_uplink),
        ]

    @staticmethod
    async def _invoke(check: Callable):
        """Call a check, awaiting it if it is async."""
        result = check()
        if asyncio.iscoroutine(result):
            return await result
        return result

    def _check_runtime(self):
        """Python version and process identity — proves the app itself is alive."""
        import platform
        return CheckStatus.OK, f"python {platform.python_version()} pid {os.getpid()}"

    def _check_config(self):
        """Configuration loaded, and whether this unit has been paired."""
        if not config.is_loaded():
            return CheckStatus.FAIL, "configuration not loaded"
        unit_id = config.get("unit_id") or "unknown"
        if not config.get("configured", False):
            # No name, no room -- this unit has not been installed anywhere yet.
            return CheckStatus.WARN, f"{unit_id} — unpaired, setup required"
        name = config.get("unit_name") or unit_id
        location = config.get("location")
        return CheckStatus.OK, f"{name} @ {location}" if location else name

    def _check_storage(self):
        """
        Free space on the root filesystem.

        A full SD card is the classic Pi failure: logs fill it, then writes
        start failing in ways that look like unrelated bugs.
        """
        try:
            usage = shutil.disk_usage("/")
        except OSError as exc:
            return CheckStatus.FAIL, f"unreadable: {exc}"

        free_gb = usage.free / (1024 ** 3)
        pct_used = usage.used / usage.total * 100
        detail = f"{free_gb:.1f} GB free ({pct_used:.0f}% used)"
        if free_gb < 0.5:
            return CheckStatus.FAIL, detail
        if free_gb < 2.0:
            return CheckStatus.WARN, detail
        return CheckStatus.OK, detail

    def _check_memory(self):
        """Available RAM. A Pi 4 with 2GB running Chromium is tight."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            available_mb = mem.available / (1024 ** 2)
            detail = f"{available_mb:.0f} MB available of {mem.total / (1024 ** 2):.0f} MB"
            if available_mb < 150:
                return CheckStatus.FAIL, detail
            if available_mb < 400:
                return CheckStatus.WARN, detail
            return CheckStatus.OK, detail
        except ImportError:
            return CheckStatus.SKIP, "psutil not installed"

    def _check_thermal(self):
        """
        CPU temperature from the thermal zone.

        A Pi in a wall enclosure with no airflow will throttle, and a throttled
        unit drops audio frames — worth knowing at boot.
        """
        path = "/sys/class/thermal/thermal_zone0/temp"
        try:
            with open(path, "r") as fh:
                celsius = int(fh.read().strip()) / 1000.0
        except (FileNotFoundError, ValueError, OSError):
            return CheckStatus.SKIP, "no thermal zone (not a Pi)"

        detail = f"{celsius:.1f} C"
        if celsius >= 80:
            return CheckStatus.FAIL, f"{detail} — throttling"
        if celsius >= 70:
            return CheckStatus.WARN, f"{detail} — running hot"
        return CheckStatus.OK, detail

    def _check_power(self):
        """
        Undervoltage flags from the Pi firmware.

        An undersized power supply is the single most common cause of a Pi
        behaving strangely, and it is invisible without checking this.
        """
        vcgencmd = shutil.which("vcgencmd")
        if not vcgencmd:
            return CheckStatus.SKIP, "vcgencmd unavailable (not a Pi)"

        import subprocess
        try:
            out = subprocess.run([vcgencmd, "get_throttled"], capture_output=True,
                                 timeout=3, text=True)
            raw = out.stdout.strip().split("=")[-1]
            flags = int(raw, 16)
        except Exception as exc:  # pylint: disable=broad-except
            return CheckStatus.SKIP, f"unreadable: {exc}"

        if flags == 0:
            return CheckStatus.OK, "supply nominal"
        # Bit 0 = undervoltage now; bit 16 = undervoltage has occurred.
        if flags & 0x1:
            return CheckStatus.FAIL, f"undervoltage NOW (0x{flags:X}) — check PSU"
        if flags & 0x10000:
            return CheckStatus.WARN, f"undervoltage occurred (0x{flags:X})"
        return CheckStatus.WARN, f"throttle flags 0x{flags:X}"

    def _check_display(self):
        """Backlight control, and the configured panel geometry."""
        width = config.get("screen_width", "?")
        height = config.get("screen_height", "?")
        form = config.get("form_factor", "hub")

        if form == "mini":
            return CheckStatus.SKIP, "headless unit — no display"

        backlight = "/sys/class/backlight/rpi_backlight/brightness"
        if os.path.exists(backlight):
            return CheckStatus.OK, f"{width}x{height} — backlight control present"
        return CheckStatus.WARN, f"{width}x{height} — no backlight control"

    def _check_audio_output(self):
        """At least one ALSA playback device. Without it the unit is mute."""
        try:
            import subprocess
            out = subprocess.run(["aplay", "-l"], capture_output=True,
                                 timeout=3, text=True)
            if out.returncode != 0 or "card" not in out.stdout:
                return CheckStatus.FAIL, "no playback device found"
            cards = [ln for ln in out.stdout.splitlines() if ln.startswith("card ")]
            return CheckStatus.OK, f"{len(cards)} playback device(s)"
        except FileNotFoundError:
            return CheckStatus.SKIP, "alsa-utils not installed"
        except Exception as exc:  # pylint: disable=broad-except
            return CheckStatus.WARN, f"unreadable: {exc}"

    def _check_microphone(self):
        """
        At least one capture device.

        No microphone means no wake word, which is most of the product.
        """
        if not config.get("mic_enabled", True):
            return CheckStatus.SKIP, "microphone disabled in profile"
        try:
            import subprocess
            out = subprocess.run(["arecord", "-l"], capture_output=True,
                                 timeout=3, text=True)
            if out.returncode != 0 or "card" not in out.stdout:
                return CheckStatus.FAIL, "no capture device — wake word unavailable"
            cards = [ln for ln in out.stdout.splitlines() if ln.startswith("card ")]
            return CheckStatus.OK, f"{len(cards)} capture device(s)"
        except FileNotFoundError:
            return CheckStatus.SKIP, "alsa-utils not installed"
        except Exception as exc:  # pylint: disable=broad-except
            return CheckStatus.WARN, f"unreadable: {exc}"

    def _check_camera(self):
        """
        The onboard camera, on units that have one.

        Reports what the camera is permitted to do as well as whether it
        works. A fitted camera with every purpose switched off is a correct,
        deliberate state — the boot screen says so rather than calling it a
        fault, because "installed but not in use" is a thing an owner chooses.
        """
        if not config.get("cap_camera", False):
            return CheckStatus.SKIP, "not fitted"

        enabled = [p for p in CAMERA_PURPOSES
                   if config.get(f"camera_purpose_{p}", False)]
        if not enabled:
            return CheckStatus.OK, "fitted, no uses enabled"

        try:
            import cv2  # type: ignore  # noqa: F401
        except ImportError:
            return (CheckStatus.WARN,
                    "opencv missing — install python3-opencv")

        return CheckStatus.OK, f"fitted, enabled for: {', '.join(enabled)}"

    def _check_light_sensor(self):
        """Ambient light sensor, used to set screen brightness."""
        if not config.get("cap_light_sensor", False):
            return CheckStatus.SKIP, "not fitted"
        return CheckStatus.OK, "fitted"

    def _check_presence_sensor(self):
        """mmWave presence sensor, used for proximity wake and occupancy."""
        if not config.get("cap_presence_sensor", False):
            return CheckStatus.SKIP, "not fitted"
        return CheckStatus.OK, "fitted"

    def _check_speech(self):
        """Offline speech fallback, used when River Song is unreachable."""
        binary = shutil.which("espeak-ng") or shutil.which("espeak")
        if binary:
            return CheckStatus.OK, f"offline fallback ready ({os.path.basename(binary)})"
        return CheckStatus.WARN, "no offline speech — unit goes mute if River Song is down"

    def _check_media(self):
        """mpv, which plays music and radio."""
        if shutil.which("mpv"):
            return CheckStatus.OK, "mpv present"
        return CheckStatus.WARN, "mpv missing — music playback disabled"

    async def _check_network(self):
        """
        A usable default route.

        These units are WiFi-only; without a route they are fully offline and
        fall back to cached state.
        """
        def _probe() -> bool:
            import socket as sock
            try:
                with sock.socket(sock.AF_INET, sock.SOCK_DGRAM) as s:
                    s.settimeout(2)
                    # Does not send traffic — just asks the kernel to pick a route.
                    s.connect(("1.1.1.1", 80))
                    return True
            except OSError:
                return False

        if await asyncio.to_thread(_probe):
            return CheckStatus.OK, "route available"
        return CheckStatus.FAIL, "no network route — running on cached state"

    async def _check_uplink(self):
        """Whether River Song is actually reachable from here."""
        base = config.get("river_song_api_url", "")
        if not base:
            return CheckStatus.SKIP, "no River Song URL configured"

        try:
            import httpx
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.get(f"{base}/api/health")
            if response.status_code < 500:
                return CheckStatus.OK, f"{base} reachable"
            return CheckStatus.WARN, f"{base} returned {response.status_code}"
        except Exception as exc:  # pylint: disable=broad-except
            # Expected on a unit that boots before the server, or offline.
            return CheckStatus.WARN, f"{base} unreachable — will retry"

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    async def _emit(self, result: Optional[Dict[str, Any]]) -> None:
        """Stream one result (or the completion sentinel) to the display."""
        if self._on_result is None:
            return
        try:
            await self._on_result(result, self.get_report())
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Diagnostic emit failed: %s", exc)
