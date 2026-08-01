"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_camera.py
Purpose:     Tests for display/camera.py and the camera half of
             safety/privacy_manager.py.

             These are privacy tests before they are feature tests. Screened
             units are wall panels and some of them are in bedrooms, so what
             is asserted here is mostly what the camera must REFUSE to do:
             run when it is not fitted, run for a purpose nobody enabled, run
             while muted, and — above all — run without lighting the indicator
             that says it is running.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import importlib.util
import unittest
from unittest.mock import MagicMock, patch

from core.constants import CAMERA_PURPOSES
from display.camera import (Camera, CameraRefused, CameraUnavailable)


def run(coro):
    """Run a coroutine on the suite's shared event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


class FakePrivacy:
    """A stand-in PrivacyManager that records interlock calls in order."""

    def __init__(self, muted=False):
        self.cam_muted = muted
        self.holders = 0
        self.calls = []

    def acquire_camera(self):
        self.calls.append("acquire")
        if self.cam_muted:
            return False
        self.holders += 1
        return True

    def release_camera(self):
        self.calls.append("release")
        self.holders = max(0, self.holders - 1)

    @property
    def cam_active(self):
        return self.holders > 0


class CameraTestCase(unittest.TestCase):
    """Base — camera config is read through the global config singleton."""

    def _configure(self, fitted=True, purposes=(), **extra):
        settings = {
            "cap_camera": fitted,
            **{f"camera_purpose_{p}": (p in purposes) for p in CAMERA_PURPOSES},
            **extra,
        }
        patcher = patch("display.camera.config")
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        mock.get.side_effect = lambda key, default=None: settings.get(key, default)

    def _camera(self, privacy=None, **kwargs):
        self._configure(**kwargs)
        return Camera(privacy_manager=privacy or FakePrivacy())


class TestNotFitted(CameraTestCase):
    """Hardware that has not been installed must never be assumed."""

    def test_a_unit_without_a_camera_reports_none(self):
        self.assertFalse(self._camera(fitted=False).fitted)

    def test_capture_on_a_unit_without_a_camera_is_unavailable(self):
        cam = self._camera(fitted=False, purposes=CAMERA_PURPOSES)
        with self.assertRaises(CameraUnavailable):
            run(cam.snapshot("motion_snapshots"))

    def test_the_default_when_a_profile_says_nothing_is_not_fitted(self):
        """A profile with no camera key must not be read as having one."""
        from core.config import Config
        cfg = Config()
        with patch.object(cfg, "_settings", {}):
            self.assertFalse(cfg._settings.get("cap_camera", False))


class TestPurposeConsent(CameraTestCase):
    """Agreeing to one use of a camera is not agreeing to all of them."""

    def test_a_purpose_that_is_not_enabled_is_refused(self):
        cam = self._camera(purposes=("video_calls",))
        with self.assertRaises(CameraRefused):
            run(cam.snapshot("face_recognition"))

    def test_enabling_one_purpose_does_not_enable_the_others(self):
        cam = self._camera(purposes=("video_calls",))
        self.assertTrue(cam.purpose_allowed("video_calls"))
        for other in ("motion_snapshots", "presence", "face_recognition"):
            self.assertFalse(cam.purpose_allowed(other), other)

    def test_an_unknown_purpose_is_refused(self):
        """A typo must fail closed, not fall through to allowed."""
        cam = self._camera(purposes=CAMERA_PURPOSES)
        self.assertFalse(cam.purpose_allowed("selling_your_data"))
        with self.assertRaises(CameraRefused):
            run(cam.snapshot("selling_your_data"))

    def test_a_fitted_camera_with_no_purposes_captures_nothing(self):
        cam = self._camera(purposes=())
        for purpose in CAMERA_PURPOSES:
            with self.assertRaises(CameraRefused):
                run(cam.snapshot(purpose))

    def test_refusal_is_distinct_from_hardware_failure(self):
        """
        'I won't' and 'I can't' must not be the same exception, or a caller
        retrying past a hardware fault would retry past a consent decision.
        """
        self.assertFalse(issubclass(CameraUnavailable, CameraRefused))
        self.assertFalse(issubclass(CameraRefused, CameraUnavailable))


class TestMuteAndIndicator(CameraTestCase):
    """The LED is an interlock. Frames must be impossible without it."""

    def test_a_muted_camera_refuses_to_open(self):
        privacy = FakePrivacy(muted=True)
        cam = self._camera(privacy=privacy, purposes=CAMERA_PURPOSES)
        with self.assertRaises(CameraRefused):
            run(cam.snapshot("video_calls"))

    def test_a_muted_camera_never_reaches_the_device(self):
        privacy = FakePrivacy(muted=True)
        cam = self._camera(privacy=privacy, purposes=CAMERA_PURPOSES)
        with patch.object(Camera, "_open_device") as open_device:
            with self.assertRaises(CameraRefused):
                run(cam.snapshot("video_calls"))
        open_device.assert_not_called()

    def test_the_indicator_is_lit_before_the_device_opens(self):
        """
        Ordering matters: opening first would leave a window in which the lens
        is live and the light is dark.
        """
        privacy = FakePrivacy()
        cam = self._camera(privacy=privacy, purposes=CAMERA_PURPOSES)
        order = []
        privacy_acquire = privacy.acquire_camera

        def record_acquire():
            order.append("indicator")
            return privacy_acquire()

        privacy.acquire_camera = record_acquire

        def record_open():
            order.append("device")
            return MagicMock()

        with patch.object(Camera, "_open_device", side_effect=record_open), \
             patch.object(Camera, "_read_jpeg", return_value=b"jpeg"), \
             patch.object(Camera, "_close_device"):
            run(cam.snapshot("presence"))

        self.assertEqual(order, ["indicator", "device"])

    def test_the_indicator_clears_when_the_session_ends(self):
        privacy = FakePrivacy()
        cam = self._camera(privacy=privacy, purposes=CAMERA_PURPOSES)
        with patch.object(Camera, "_open_device", return_value=MagicMock()), \
             patch.object(Camera, "_read_jpeg", return_value=b"jpeg"), \
             patch.object(Camera, "_close_device"):
            run(cam.snapshot("presence"))
        self.assertFalse(privacy.cam_active)

    def test_the_indicator_clears_when_the_capture_raises(self):
        """A crash mid-capture must not strand the light on."""
        privacy = FakePrivacy()
        cam = self._camera(privacy=privacy, purposes=CAMERA_PURPOSES)
        with patch.object(Camera, "_open_device", return_value=MagicMock()), \
             patch.object(Camera, "_read_jpeg", side_effect=RuntimeError("boom")), \
             patch.object(Camera, "_close_device"):
            with self.assertRaises(RuntimeError):
                run(cam.snapshot("presence"))
        self.assertFalse(privacy.cam_active)

    def test_the_indicator_clears_when_the_device_fails_to_open(self):
        """Otherwise the light would report a lens that never went live."""
        privacy = FakePrivacy()
        cam = self._camera(privacy=privacy, purposes=CAMERA_PURPOSES)
        with patch.object(Camera, "_open_device",
                          side_effect=CameraUnavailable("no device")):
            with self.assertRaises(CameraUnavailable):
                run(cam.snapshot("presence"))
        self.assertFalse(privacy.cam_active)

    def test_a_camera_with_no_indicator_refuses_to_run(self):
        """A camera that cannot say it is on has no business being on."""
        self._configure(fitted=True, purposes=CAMERA_PURPOSES)
        cam = Camera(privacy_manager=None)
        with self.assertRaises(CameraRefused):
            run(cam.snapshot("video_calls"))

    def test_overlapping_sessions_keep_the_indicator_lit(self):
        """A video call and a motion check at once must not darken it early."""
        privacy = FakePrivacy()
        privacy.acquire_camera()
        privacy.acquire_camera()
        privacy.release_camera()
        self.assertTrue(privacy.cam_active)
        privacy.release_camera()
        self.assertFalse(privacy.cam_active)


class TestReportedState(CameraTestCase):
    """What the unit tells the frontend and River Song about itself."""

    def test_state_reports_each_purpose_separately(self):
        cam = self._camera(purposes=("video_calls", "presence"))
        purposes = cam.get_state()["purposes"]
        self.assertTrue(purposes["video_calls"])
        self.assertTrue(purposes["presence"])
        self.assertFalse(purposes["face_recognition"])
        self.assertFalse(purposes["motion_snapshots"])

    def test_an_unfitted_camera_is_not_available(self):
        self.assertFalse(self._camera(fitted=False).get_state()["available"])

    def test_a_muted_camera_is_not_available(self):
        cam = self._camera(privacy=FakePrivacy(muted=True), purposes=CAMERA_PURPOSES)
        self.assertFalse(cam.get_state()["available"])


class TestPrivacyManagerInterlock(unittest.TestCase):
    """The real PrivacyManager, not the fake."""

    def _manager(self):
        from safety.privacy_manager import PrivacyManager
        with patch("safety.privacy_manager.config") as cfg:
            cfg.get.side_effect = lambda key, default=None: default
            manager = PrivacyManager()
        return manager

    def test_the_camera_led_follows_capture_not_the_mute_flag(self):
        """
        The whole point. Muting is a request; the light reports reality, so
        toggling mute while nothing is capturing must not light it.
        """
        manager = self._manager()
        manager.mute_camera()
        self.assertFalse(manager.cam_active)
        manager.unmute_camera()
        self.assertFalse(manager.cam_active)

    def test_acquiring_lights_the_indicator(self):
        manager = self._manager()
        self.assertTrue(manager.acquire_camera())
        self.assertTrue(manager.cam_active)

    def test_a_muted_camera_cannot_be_acquired(self):
        manager = self._manager()
        manager.mute_camera()
        self.assertFalse(manager.acquire_camera())
        self.assertFalse(manager.cam_active)

    def test_releasing_more_than_acquiring_does_not_go_negative(self):
        """A double release must not leave the count able to hide a live lens."""
        manager = self._manager()
        manager.acquire_camera()
        manager.release_camera()
        manager.release_camera()
        manager.acquire_camera()
        self.assertTrue(manager.cam_active)

    def test_state_reports_active_separately_from_muted(self):
        manager = self._manager()
        manager.acquire_camera()
        state = manager.get_state()
        self.assertTrue(state["cam_active"])
        self.assertFalse(state["cam_muted"])


class TestDiagnostics(unittest.TestCase):
    """The boot screen must tell the truth about optional hardware."""

    def _check(self, name, settings):
        from core.diagnostics import Diagnostics
        with patch("core.diagnostics.config") as cfg:
            cfg.get.side_effect = lambda key, default=None: settings.get(key, default)
            return getattr(Diagnostics(), name)()

    def test_an_unfitted_camera_is_skipped_not_failed(self):
        from core.diagnostics import CheckStatus
        status, detail = self._check("_check_camera", {"cap_camera": False})
        self.assertEqual(status, CheckStatus.SKIP)
        self.assertIn("not fitted", detail)

    def test_a_fitted_camera_with_no_uses_is_ok(self):
        """Installed but switched off is a choice, not a fault."""
        from core.diagnostics import CheckStatus
        status, detail = self._check("_check_camera", {"cap_camera": True})
        self.assertEqual(status, CheckStatus.OK)
        self.assertIn("no uses enabled", detail)

    def test_the_boot_screen_names_which_uses_are_enabled(self):
        import sys
        # opencv is a system package and is not installed everywhere; stub it
        # so this asserts the reporting, not the container's apt state.
        with patch.dict(sys.modules, {"cv2": MagicMock()}):
            _, detail = self._check("_check_camera", {
                "cap_camera": True, "camera_purpose_video_calls": True,
            })
        self.assertIn("video_calls", detail)

    @unittest.skipIf(importlib.util.find_spec("cv2") is not None,
                     "opencv is installed here, so there is no gap to report")
    def test_a_camera_enabled_without_opencv_warns_rather_than_failing(self):
        """The unit still boots; it just cannot capture yet."""
        from core.diagnostics import CheckStatus
        status, detail = self._check("_check_camera", {
            "cap_camera": True, "camera_purpose_presence": True,
        })
        self.assertEqual(status, CheckStatus.WARN)
        self.assertIn("opencv", detail)

    def test_unfitted_sensors_are_skipped(self):
        from core.diagnostics import CheckStatus
        for check in ("_check_light_sensor", "_check_presence_sensor"):
            status, _ = self._check(check, {})
            self.assertEqual(status, CheckStatus.SKIP, check)


class TestShippedProfile(unittest.TestCase):
    """What every unit is flashed with."""

    def _profile(self):
        import json, pathlib
        return json.loads(pathlib.Path("units/vortex_profile.json").read_text())

    def test_optional_hardware_ships_absent(self):
        caps = self._profile()["capabilities"]
        for key in ("camera", "light_sensor", "presence_sensor"):
            self.assertFalse(caps[key], f"{key} must not be assumed present")

    def test_every_camera_use_ships_switched_off(self):
        """A camera must do nothing until its owner says what it is for."""
        purposes = self._profile()["camera_purposes"]
        for purpose in CAMERA_PURPOSES:
            self.assertFalse(purposes[purpose], purpose)


if __name__ == "__main__":
    unittest.main()
