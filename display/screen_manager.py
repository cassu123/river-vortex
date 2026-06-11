"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        display/screen_manager.py
Purpose:     Top-level display subsystem coordinator. Manages screen brightness,
             rotation, power state, and transitions between display modes
             (ambient, dashboard, camera viewer, notification overlay).
             Communicates with the React frontend via WebSocket events.
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
    AMBIENT_MODE_TIMEOUT_SECONDS,
    SCREEN_BRIGHTNESS_AMBIENT,
    SCREEN_BRIGHTNESS_DEFAULT,
    SCREEN_BRIGHTNESS_MAX,
    SCREEN_BRIGHTNESS_MIN,
)

logger = logging.getLogger(__name__)


class DisplayMode:
    """Enumeration of available display modes."""
    SETUP = "setup"
    AMBIENT = "ambient"
    DASHBOARD = "dashboard"
    DEVICES = "devices"
    CAMERAS = "cameras"
    INTERCOM = "intercom"
    NOTIFICATION = "notification"
    ROUTINE = "routine"


class ScreenManager:
    """
    Manages the River Vortex display hardware and mode transitions.

    Controls:
    - Screen brightness via sysfs (Raspberry Pi backlight)
    - Display mode routing (ambient ↔ dashboard ↔ cameras ↔ intercom)
    - Idle timeout → ambient mode transition
    - Screen on/off for power saving

    The React frontend is the actual rendering layer. ScreenManager
    communicates mode changes to the frontend via the FastAPI WebSocket
    endpoint at /api/display/events.
    """

    def __init__(self) -> None:
        """Initialize ScreenManager."""
        self._current_mode: str = DisplayMode.AMBIENT
        self._brightness: int = config.get("screen_brightness", SCREEN_BRIGHTNESS_DEFAULT)
        self._ambient_timeout: int = config.get("ambient_timeout", AMBIENT_MODE_TIMEOUT_SECONDS)
        self._idle_timer_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._screen_on: bool = True

        # Sysfs path for Pi backlight brightness control
        self._backlight_path: str = (
            "/sys/class/backlight/rpi_backlight/brightness"
        )

    async def start(self) -> None:
        """
        Start the screen manager and initialize the display.

        Sets initial brightness. If this unit has not yet been paired with
        River Song, the display starts in Setup mode (showing the pairing
        PIN) and the ambient idle timer is not started — the setup screen
        stays up at full brightness until pairing completes.
        """
        self._running = True
        self._apply_brightness(self._brightness)

        if not config.get("configured", False):
            self._current_mode = DisplayMode.SETUP
        else:
            self._reset_idle_timer()

        logger.info(
            "ScreenManager started (mode=%s, brightness=%d%%).",
            self._current_mode,
            self._brightness,
        )

    async def stop(self) -> None:
        """Stop the screen manager and cancel the idle timer."""
        self._running = False
        if self._idle_timer_task:
            self._idle_timer_task.cancel()
            try:
                await self._idle_timer_task
            except asyncio.CancelledError:
                pass
        logger.info("ScreenManager stopped.")

    # ─────────────────────────────────────────────────────────────────────────
    # Mode Control
    # ─────────────────────────────────────────────────────────────────────────

    async def set_mode(self, mode: str) -> None:
        """
        Switch the display to the specified mode.

        Resets the idle timer on any non-ambient mode switch.

        Args:
            mode: One of the DisplayMode constants.
        """
        if mode == self._current_mode:
            return

        logger.info("Display mode: %s → %s", self._current_mode, mode)
        self._current_mode = mode

        if mode == DisplayMode.AMBIENT:
            self._apply_brightness(SCREEN_BRIGHTNESS_AMBIENT)
        else:
            self._apply_brightness(self._brightness)
            self._reset_idle_timer()

        await self._notify_frontend(mode)

    async def go_ambient(self) -> None:
        """Transition to ambient (clock/weather) mode."""
        await self.set_mode(DisplayMode.AMBIENT)

    async def go_dashboard(self) -> None:
        """Transition to the main dashboard."""
        await self.set_mode(DisplayMode.DASHBOARD)

    async def go_cameras(self) -> None:
        """Transition to the camera viewer."""
        await self.set_mode(DisplayMode.CAMERAS)

    def register_activity(self) -> None:
        """
        Register user activity (touch, voice) to reset the idle timer.

        Call this whenever the user interacts with the device.
        """
        if self._current_mode == DisplayMode.AMBIENT:
            asyncio.create_task(self.go_dashboard())
        self._reset_idle_timer()

    # ─────────────────────────────────────────────────────────────────────────
    # Brightness
    # ─────────────────────────────────────────────────────────────────────────

    def set_brightness(self, level: int) -> None:
        """
        Set screen brightness.

        Args:
            level: Brightness percentage (SCREEN_BRIGHTNESS_MIN–SCREEN_BRIGHTNESS_MAX).
        """
        self._brightness = max(SCREEN_BRIGHTNESS_MIN, min(SCREEN_BRIGHTNESS_MAX, level))
        self._apply_brightness(self._brightness)

    def get_brightness(self) -> int:
        """Return the current brightness level."""
        return self._brightness

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    def _apply_brightness(self, level: int) -> None:
        """
        Write brightness to the Pi backlight sysfs interface.

        Falls back to xrandr on non-Pi hardware. Silently skips if neither
        is available (e.g., headless development environment).

        Args:
            level: Brightness percentage (0–100).
        """
        # Convert percentage to 0–255 range for sysfs
        raw_value = int(level * 255 / 100)
        try:
            with open(self._backlight_path, "w") as fh:
                fh.write(str(raw_value))
            logger.debug("Backlight brightness set to %d (%d%%).", raw_value, level)
        except (FileNotFoundError, PermissionError):
            # Not a Pi or no backlight — try xrandr
            try:
                subprocess.run(
                    ["xrandr", "--output", "HDMI-1", "--brightness", f"{level / 100:.2f}"],
                    capture_output=True,
                    timeout=3,
                )
            except Exception:  # pylint: disable=broad-except
                logger.debug("Brightness control not available on this hardware.")

    def _reset_idle_timer(self) -> None:
        """Cancel and restart the ambient mode idle timer."""
        if self._idle_timer_task:
            self._idle_timer_task.cancel()
        if self._running:
            self._idle_timer_task = asyncio.create_task(
                self._idle_timeout_handler(), name="screen-idle-timer"
            )

    async def _idle_timeout_handler(self) -> None:
        """
        Wait for the idle timeout, then switch to ambient mode.

        Cancelled and restarted by _reset_idle_timer() on any activity.
        """
        try:
            await asyncio.sleep(self._ambient_timeout)
            logger.debug("Idle timeout reached — switching to ambient mode.")
            await self.go_ambient()
        except asyncio.CancelledError:
            pass

    async def _notify_frontend(self, mode: str) -> None:
        """
        Notify the React frontend of a display mode change via WebSocket.

        Args:
            mode: The new display mode string.
        """
        from core.ws_hub import ws_hub
        await ws_hub.broadcast({"type": "navigate", "page": mode})
        logger.debug("Frontend notified of mode change: %s", mode)
