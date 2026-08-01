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

import logging
from typing import Optional

from core.config import config
from core.constants import PRIVACY_CAM_ACTIVE_GPIO_PIN, PRIVACY_MIC_MUTE_GPIO_PIN

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

    def __init__(self) -> None:
        """Initialize PrivacyManager."""
        self._mic_muted: bool = config.get("privacy_mic_mute_on_startup", False)
        self._cam_muted: bool = config.get("privacy_cam_mute_on_startup", False)
        # How many capture sessions currently hold the camera open. The LED
        # follows this count, not the mute flag — see _apply_cam_state.
        self._cam_active_holders: int = 0
        self._gpio_available: bool = False
        self._gpio = None

    async def start(self) -> None:
        """
        Initialize GPIO for hardware LED indicators.

        Falls back gracefully if GPIO is not available (e.g., non-Pi hardware).
        """
        self._init_gpio()
        self._apply_mic_state()
        self._apply_cam_state()
        logger.info(
            "PrivacyManager started. Mic muted: %s | Camera muted: %s",
            self._mic_muted,
            self._cam_muted,
        )

    async def stop(self) -> None:
        """Release GPIO resources."""
        if self._gpio_available and self._gpio:
            try:
                self._gpio.cleanup()
            except Exception:  # pylint: disable=broad-except
                pass
        logger.info("PrivacyManager stopped.")

    # ─────────────────────────────────────────────────────────────────────────
    # Microphone Privacy
    # ─────────────────────────────────────────────────────────────────────────

    def mute_microphone(self) -> None:
        """
        Mute the microphone and activate the hardware LED indicator.

        This sets the software mute flag. The Microphone class checks this
        flag and returns silence frames when muted.
        """
        self._mic_muted = True
        self._apply_mic_state()
        logger.info("Microphone muted by privacy manager.")

    def unmute_microphone(self) -> None:
        """Unmute the microphone and deactivate the LED indicator."""
        self._mic_muted = False
        self._apply_mic_state()
        logger.info("Microphone unmuted by privacy manager.")

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
        """Return True if the microphone is currently muted."""
        return self._mic_muted

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
            "mic_muted": self._mic_muted,
            "cam_muted": self._cam_muted,
            # Shown on screen as well as on the LED, so someone looking at the
            # panel does not have to trust a single indicator.
            "cam_active": self.cam_active,
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
                # LED ON = muted (privacy active)
                self._gpio.output(PRIVACY_MIC_MUTE_GPIO_PIN, self._mic_muted)
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
