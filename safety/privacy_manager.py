"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        safety/privacy_manager.py
Purpose:     Hardware and software privacy controls for microphone and camera.
             Manages physical mute LED indicators via GPIO, enforces software
             mute state, and provides a privacy API for the frontend and voice
             commands. Privacy state is always visible to the user.
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
from core.constants import (PRIVACY_CAM_ACTIVE_GPIO_PIN,
                            PRIVACY_MIC_MUTE_GPIO_PIN,
                            PRIVACY_MIC_SWITCH_GPIO_PIN,
                            PRIVACY_SWITCH_POLL_SECONDS)

logger = logging.getLogger(__name__)


class PrivacyManager:
    """
    Manages microphone and camera privacy state for River Vortex.

    Controls:
    - Software mute (blocks audio capture in Microphone class)
    - Hardware LED indicator via GPIO (shows physical mute state to user)
    - Privacy state persistence across restarts

    Privacy principle:
        The user must always be able to see whether the mic/camera is active.
        Hardware LED indicators are driven by GPIO — they cannot be spoofed
        by software bugs in other subsystems.
    """

    def __init__(self, on_change=None) -> None:
        """
        Args:
            on_change: Awaited with the privacy state whenever it changes, so
                the screen can put up the "Microphone muted" banner the moment
                the switch is flipped rather than on the next poll from the UI.
        """
        self._mic_muted: bool = config.get("privacy_mic_mute_on_startup", False)
        self._cam_muted: bool = config.get("privacy_cam_mute_on_startup", False)
        # How many capture sessions currently hold the camera open. The LED
        # follows this count, not the mute flag — see _apply_cam_state.
        self._cam_active_holders: int = 0
        self._gpio_available: bool = False
        self._gpio = None
        self._on_change = on_change

        # The physical switch. None means no switch is fitted (or GPIO is
        # unavailable), in which case mute is software-only as before.
        self._switch_muted: Optional[bool] = None
        self._switch_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """
        Initialize GPIO, then start watching the physical mute switch.

        Falls back gracefully if GPIO is not available (e.g., non-Pi hardware).
        """
        self._init_gpio()
        self._read_switch()          # Before anything can capture audio.
        self._apply_mic_state()
        self._apply_cam_state()

        if self._switch_muted is not None:
            self._switch_task = asyncio.create_task(
                self._watch_switch(), name="privacy-mute-switch")

        logger.info(
            "PrivacyManager started. Mic muted: %s (switch: %s) | Camera muted: %s",
            self.mic_muted,
            "muted" if self._switch_muted else
            ("open" if self._switch_muted is False else "not fitted"),
            self._cam_muted,
        )

    async def stop(self) -> None:
        """Release GPIO resources."""
        if self._switch_task and not self._switch_task.done():
            self._switch_task.cancel()
        if self._gpio_available and self._gpio:
            try:
                self._gpio.cleanup()
            except Exception:  # pylint: disable=broad-except
                pass
        logger.info("PrivacyManager stopped.")

    # ─────────────────────────────────────────────────────────────────────────
    # The physical mute switch
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def switch_fitted(self) -> bool:
        """True if this unit has a physical mute switch wired up."""
        return self._switch_muted is not None

    @property
    def switch_muted(self) -> bool:
        """True if the physical switch is currently in the muted position."""
        return bool(self._switch_muted)

    def _read_switch(self) -> None:
        """
        Read the switch position.

        Leaves _switch_muted as None when no switch is fitted or GPIO is
        unavailable, which keeps mute software-only on those units rather than
        inventing a switch that is not there.
        """
        if not (self._gpio_available and self._gpio):
            return
        try:
            # Pulled up: closed to ground (flipped to mute) reads LOW.
            self._switch_muted = not bool(
                self._gpio.input(PRIVACY_MIC_SWITCH_GPIO_PIN))
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Mute switch unreadable: %s", exc)
            self._switch_muted = None

    async def _watch_switch(self) -> None:
        """
        Poll the switch and react the moment it moves.

        Polling rather than edge interrupts because RPi.GPIO's callbacks fire
        on a library-owned thread, and this needs to await the change
        notification on the main loop. At five reads a second the latency is
        imperceptible and the cost is nothing.
        """
        try:
            while True:
                await asyncio.sleep(PRIVACY_SWITCH_POLL_SECONDS)
                before = self._switch_muted
                self._read_switch()
                if self._switch_muted == before:
                    continue

                logger.info("Physical mute switch moved to %s.",
                            "MUTED" if self._switch_muted else "open")
                self._apply_mic_state()
                await self._notify()
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Mute switch watcher stopped: %s", exc)

    async def _notify(self) -> None:
        """Tell whoever is listening that privacy state changed."""
        if self._on_change is None:
            return
        try:
            await self._on_change(self.get_state())
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Privacy state notification failed: %s", exc)

    # ─────────────────────────────────────────────────────────────────────────
    # Microphone Privacy
    # ─────────────────────────────────────────────────────────────────────────

    def mute_microphone(self) -> None:
        """
        Mute the microphone and light the indicator.

        Always allowed. Software can always make things MORE private; what it
        cannot do is make them less (see unmute_microphone).
        """
        self._mic_muted = True
        self._apply_mic_state()
        logger.info("Microphone muted by privacy manager.")

    def unmute_microphone(self) -> bool:
        """
        Unmute the microphone — unless the physical switch says otherwise.

        This is the whole reason the switch exists. A setting you can toggle
        in an app is a preference; a switch you can see is a promise, and a
        promise software can quietly revoke is not one. So while the switch is
        in the muted position this refuses, and the unit stays muted no matter
        what the touchscreen, River Song or a voice command asks for.

        Returns:
            True if the microphone is now live. False means the switch is
            holding it muted.
        """
        if self._switch_muted:
            logger.info("Unmute refused — the physical mute switch is on.")
            return False
        self._mic_muted = False
        self._apply_mic_state()
        logger.info("Microphone unmuted by privacy manager.")
        return True

    def toggle_microphone(self) -> bool:
        """
        Toggle microphone mute state.

        Returns:
            True if the microphone is now muted, False if unmuted.
        """
        if self._mic_muted:
            self.unmute_microphone()
        else:
            self.mute_microphone()
        return self._mic_muted

    @property
    def mic_muted(self) -> bool:
        """
        Return True if the microphone is currently muted.

        The switch wins. If it is in the muted position the microphone is
        muted, whatever the software flag says — that is what makes it worth
        having, and reading it here means every caller gets the truth without
        having to remember to ask about the switch separately.
        """
        return bool(self._switch_muted) or self._mic_muted

    # ─────────────────────────────────────────────────────────────────────────
    # Camera Privacy
    # ─────────────────────────────────────────────────────────────────────────

    def mute_camera(self) -> None:
        """
        Block camera access.

        Note this does NOT touch the LED. The LED reports whether the lens is
        live, and muting while a session is somehow still open must not darken
        it — the light has to keep telling the truth even when the software is
        in a state it should not be in.
        """
        self._cam_muted = True
        logger.info("Camera muted by privacy manager.")

    def unmute_camera(self) -> None:
        """Allow camera access. Does not itself open the camera."""
        self._cam_muted = False
        logger.info("Camera unmuted by privacy manager.")

    # ── Capture interlock ────────────────────────────────────────────────────
    # display/camera.py calls these around every capture. They are the ONLY
    # way the camera LED changes, which is what makes the indicator an
    # interlock rather than a hint: acquiring the camera lights it, and there
    # is no code path that gets frames without going through here.

    def acquire_camera(self) -> bool:
        """
        Register that a capture session is opening the camera, and light the
        indicator BEFORE any frame can be read.

        Returns:
            False if the camera is muted, in which case the caller must not
            open the device.
        """
        if self._cam_muted:
            logger.info("Camera acquisition refused — muted.")
            return False
        self._cam_active_holders += 1
        self._apply_cam_state()
        return True

    def release_camera(self) -> None:
        """Register that a capture session has closed the camera."""
        self._cam_active_holders = max(0, self._cam_active_holders - 1)
        self._apply_cam_state()

    @property
    def cam_active(self) -> bool:
        """True while at least one capture session holds the camera open."""
        return self._cam_active_holders > 0

    def toggle_camera(self) -> bool:
        """
        Toggle camera mute state.

        Returns:
            True if the camera is now muted, False if unmuted.
        """
        if self._cam_muted:
            self.unmute_camera()
        else:
            self.mute_camera()
        return self._cam_muted

    @property
    def cam_muted(self) -> bool:
        """Return True if the camera is currently muted."""
        return self._cam_muted

    def get_state(self) -> dict:
        """
        Return the current privacy state.

        Returns:
            Dict with mic_muted and cam_muted booleans.
        """
        return {
            "mic_muted": self.mic_muted,
            "cam_muted": self._cam_muted,
            # Shown on screen as well as on the LED, so someone looking at the
            # panel does not have to trust a single indicator.
            "cam_active": self.cam_active,
            # Whether a physical switch is fitted, and where it is. The screen
            # needs both: a unit with no switch should not imply it has one,
            # and a unit whose switch is on must show the toggle as locked
            # rather than as something the user failed to turn off.
            "mic_switch_fitted": self.switch_fitted,
            "mic_switch_muted": self.switch_muted,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    def _init_gpio(self) -> None:
        """
        Initialize RPi.GPIO for hardware LED control.

        Silently skips if RPi.GPIO is not available (non-Pi hardware).
        """
        try:
            import RPi.GPIO as GPIO  # type: ignore
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(PRIVACY_MIC_MUTE_GPIO_PIN, GPIO.OUT)
            GPIO.setup(PRIVACY_CAM_ACTIVE_GPIO_PIN, GPIO.OUT)
            # The one input: the physical mute switch, pulled up so an
            # unwired pin reads "not muted" rather than floating.
            GPIO.setup(PRIVACY_MIC_SWITCH_GPIO_PIN, GPIO.IN,
                       pull_up_down=GPIO.PUD_UP)
            self._gpio = GPIO
            self._gpio_available = True
            logger.debug(
                "GPIO initialized. Mic LED: pin %d | Cam LED: pin %d",
                PRIVACY_MIC_MUTE_GPIO_PIN,
                PRIVACY_CAM_ACTIVE_GPIO_PIN,
            )
        except (ImportError, RuntimeError):
            logger.debug("RPi.GPIO not available — hardware LED indicators disabled.")
            self._gpio_available = False

    def _apply_mic_state(self) -> None:
        """Drive the microphone mute LED to match the current mute state."""
        if self._gpio_available and self._gpio:
            try:
                # LED ON = muted (privacy active). Reads the property, not
                # the flag, so the physical switch lights it too.
                self._gpio.output(PRIVACY_MIC_MUTE_GPIO_PIN, self.mic_muted)
            except Exception as exc:
                logger.debug("GPIO mic LED error: %s", exc)

    def _apply_cam_state(self) -> None:
        """
        Drive the camera LED to match whether the lens is actually live.

        HIGH = camera active. The inverse of the mic LED, deliberately — see
        PRIVACY_CAM_ACTIVE_GPIO_PIN in core/constants.py.
        """
        if self._gpio_available and self._gpio:
            try:
                self._gpio.output(PRIVACY_CAM_ACTIVE_GPIO_PIN, self.cam_active)
            except Exception as exc:
                logger.debug("GPIO cam LED error: %s", exc)
