"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        display/camera.py
Purpose:     The onboard camera on screened units — and the only way to get a
             frame out of it.

             Screened Vortex units are wall panels, and some of them are in
             bedrooms. That makes this the most sensitive code in the repo, so
             it is built around three rules rather than around features:

             1. NOT FITTED IS THE DEFAULT. A unit reports no camera unless its
                profile says otherwise. Hardware that has not been installed
                must never be assumed.

             2. EVERY CAPTURE DECLARES A PURPOSE, AND EACH PURPOSE IS CONSENTED
                SEPARATELY. Agreeing to video calls is not agreeing to have
                your face matched against a roster. A capture for a purpose the
                owner has not enabled is refused here, not filtered later.

             3. THE INDICATOR IS AN INTERLOCK, NOT A HINT. Acquiring the camera
                lights the LED in the same call that opens the device, and the
                LED stays lit until the session closes. There is deliberately
                no way to read a frame that does not pass through
                CameraSession, so software cannot capture with the light off.

             Nothing here decides what an image MEANS. Motion detection is a
             brightness delta, nothing more; faces go to River Song for
             matching. A wall panel does not get to be the thing that decides
             who you are.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from core.config import config
from core.constants import (CAMERA_DEVICE_INDEX, CAMERA_PURPOSES,
                            CAMERA_SNAPSHOT_HEIGHT, CAMERA_SNAPSHOT_WIDTH,
                            CAMERA_WARMUP_FRAMES)

logger = logging.getLogger(__name__)


class CameraError(Exception):
    """Raised when a capture cannot be performed."""


class CameraUnavailable(CameraError):
    """No camera is fitted, or it could not be opened."""


class CameraRefused(CameraError):
    """
    The capture was refused on privacy grounds — muted, or for a purpose the
    owner has not enabled.

    Deliberately distinct from CameraUnavailable: "I won't" and "I can't" are
    different answers, and a caller that retries on hardware failure must not
    retry its way around a consent decision.
    """


class CameraSession:
    """
    A held-open camera, scoped to one purpose.

    Use as an async context manager so the indicator is guaranteed to clear
    even if the body raises:

        async with camera.session("motion_snapshots") as cam:
            frame = await cam.frame()
    """

    def __init__(self, camera: "Camera", purpose: str) -> None:
        self._camera = camera
        self._purpose = purpose
        self._device = None

    async def __aenter__(self) -> "CameraSession":
        await self._camera._open_session(self)
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._camera._close_session(self)

    async def frame(self) -> bytes:
        """
        Read one frame as encoded JPEG bytes.

        Raises:
            CameraUnavailable: If the device stopped responding mid-session.
        """
        if self._device is None:
            raise CameraUnavailable("Camera session is not open.")
        return await asyncio.get_event_loop().run_in_executor(
            None, self._camera._read_jpeg, self._device
        )

    @property
    def purpose(self) -> str:
        """What this session declared it was for."""
        return self._purpose


class Camera:
    """
    The onboard camera, if this unit has one.

    Usage:
        camera = Camera(privacy_manager=privacy)
        if camera.available:
            async with camera.session("motion_snapshots") as cam:
                jpeg = await cam.frame()
    """

    def __init__(self, privacy_manager: Any = None) -> None:
        """
        Args:
            privacy_manager: The PrivacyManager whose interlock guards every
                capture. Passing None leaves the camera permanently
                unavailable — a camera with no indicator to light must not
                run at all, so this fails closed rather than open.
        """
        self._privacy = privacy_manager
        self._lock = asyncio.Lock()
        self._open_count = 0

    # ─────────────────────────────────────────────────────────────────────────
    # Capability
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def fitted(self) -> bool:
        """True if this unit's profile declares a camera."""
        return bool(config.get("cap_camera", False))

    @property
    def available(self) -> bool:
        """
        True if a capture could succeed right now — fitted, not muted, and
        with an indicator available to light.
        """
        if not self.fitted or self._privacy is None:
            return False
        return not self._privacy.cam_muted

    def purpose_allowed(self, purpose: str) -> bool:
        """
        Whether the owner has enabled this particular use of the camera.

        Args:
            purpose: One of CAMERA_PURPOSES.
        """
        if purpose not in CAMERA_PURPOSES:
            return False
        return bool(config.get(f"camera_purpose_{purpose}", False))

    def get_state(self) -> Dict[str, Any]:
        """Report what this unit's camera can do, for the frontend and API."""
        return {
            "fitted": self.fitted,
            "available": self.available,
            "active": bool(self._privacy and self._privacy.cam_active),
            "muted": bool(self._privacy and self._privacy.cam_muted),
            "purposes": {p: self.purpose_allowed(p) for p in CAMERA_PURPOSES},
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Capture
    # ─────────────────────────────────────────────────────────────────────────

    def session(self, purpose: str) -> CameraSession:
        """
        Open a capture session for a declared purpose.

        Args:
            purpose: One of CAMERA_PURPOSES. Checked against the owner's
                consent flags when the session is entered.

        Returns:
            An async context manager. Nothing is opened until it is entered.
        """
        return CameraSession(self, purpose)

    async def snapshot(self, purpose: str) -> bytes:
        """
        Convenience wrapper: one frame, session opened and closed around it.

        Args:
            purpose: One of CAMERA_PURPOSES.

        Returns:
            JPEG bytes.
        """
        async with self.session(purpose) as cam:
            return await cam.frame()

    # ─────────────────────────────────────────────────────────────────────────
    # Internals — the single choke point every frame passes through
    # ─────────────────────────────────────────────────────────────────────────

    async def _open_session(self, session: CameraSession) -> None:
        """
        Validate, light the indicator, then open the device — in that order.

        The ordering matters. Lighting the LED after opening would leave a
        window in which the lens is live and dark, which is precisely the
        state the indicator exists to make impossible.
        """
        if not self.fitted:
            raise CameraUnavailable("This unit has no camera fitted.")

        if self._privacy is None:
            # No indicator means no capture. A camera that cannot tell anyone
            # it is on has no business being on.
            raise CameraRefused("No privacy indicator available.")

        if not self.purpose_allowed(session.purpose):
            raise CameraRefused(
                f"Camera use for '{session.purpose}' is not enabled on this unit."
            )

        async with self._lock:
            if not self._privacy.acquire_camera():
                raise CameraRefused("The camera is muted.")

            try:
                session._device = await asyncio.get_event_loop().run_in_executor(
                    None, self._open_device
                )
            except Exception:
                # Never leave the indicator lit for a device that failed to
                # open — the light would be reporting a lens that is not live.
                self._privacy.release_camera()
                raise

            self._open_count += 1
            logger.info("Camera opened for '%s'.", session.purpose)

    async def _close_session(self, session: CameraSession) -> None:
        """Close the device and clear the indicator."""
        async with self._lock:
            if session._device is not None:
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None, self._close_device, session._device
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("Camera close failed: %s", exc)
                session._device = None

            if self._privacy is not None:
                self._privacy.release_camera()
            logger.debug("Camera released from '%s'.", session.purpose)

    # ── Device layer ─────────────────────────────────────────────────────────
    # Split out so the interlock above can be tested without hardware, and so
    # swapping OpenCV for picamera2 later touches only these three methods.

    def _open_device(self):
        """Open the capture device. Blocking — run in an executor."""
        try:
            import cv2  # type: ignore
        except ImportError as exc:
            raise CameraUnavailable(
                "OpenCV is not installed — camera capture unavailable. "
                "Install with: sudo apt install python3-opencv"
            ) from exc

        device = cv2.VideoCapture(CAMERA_DEVICE_INDEX)
        if not device.isOpened():
            device.release()
            raise CameraUnavailable(
                f"Camera device {CAMERA_DEVICE_INDEX} could not be opened."
            )

        device.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_SNAPSHOT_WIDTH)
        device.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_SNAPSHOT_HEIGHT)

        # Sensors need a moment to settle; the first frames come out dark.
        for _ in range(CAMERA_WARMUP_FRAMES):
            device.read()

        return device

    def _read_jpeg(self, device) -> bytes:
        """Read and encode one frame. Blocking — run in an executor."""
        import cv2  # type: ignore

        ok, frame = device.read()
        if not ok or frame is None:
            raise CameraUnavailable("Camera returned no frame.")

        ok, buffer = cv2.imencode(".jpg", frame)
        if not ok:
            raise CameraUnavailable("Frame could not be encoded.")
        return buffer.tobytes()

    def _close_device(self, device) -> None:
        """Release the capture device. Blocking — run in an executor."""
        device.release()


# Module-level singleton, wired with the privacy manager at startup by
# core/main.py. Left unwired it reports no camera, which is the safe default.
camera = Camera()
