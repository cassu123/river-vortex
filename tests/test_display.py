"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_display.py
Purpose:     Unit tests for the display subsystem — screen manager, ambient
             mode, notification display, and camera viewer. All hardware
             dependencies (GPIO, sysfs backlight) are mocked.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def run_async(coro):
    """Run an async coroutine synchronously in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────────
# ScreenManager tests
# ─────────────────────────────────────────────────────────────────────────────

class TestScreenManager(unittest.TestCase):
    """Tests for display/screen_manager.py — ScreenManager."""

    def _make_manager(self):
        """Create a ScreenManager with backlight writes patched out."""
        from core.config import config
        from display.screen_manager import ScreenManager

        # These tests assume a paired unit (AMBIENT mode + idle timer on
        # start), not the unpaired Setup-mode startup path.
        config.set("configured", True)

        manager = ScreenManager()
        manager._apply_brightness = MagicMock()
        manager._notify_frontend = AsyncMock()
        return manager

    def test_start_sets_running(self):
        """start() should set _running to True."""
        manager = self._make_manager()
        run_async(manager.start())
        self.assertTrue(manager._running)
        run_async(manager.stop())

    def test_start_enters_setup_mode_when_unconfigured(self):
        """An unpaired unit should start in Setup mode without an idle timer."""
        from core.config import config
        from display.screen_manager import DisplayMode

        manager = self._make_manager()
        config.set("configured", False)
        try:
            run_async(manager.start())
            self.assertEqual(manager._current_mode, DisplayMode.SETUP)
            self.assertIsNone(manager._idle_timer_task)
            run_async(manager.stop())
        finally:
            config.set("configured", True)

    def test_set_mode_changes_current_mode(self):
        """set_mode() should update _current_mode."""
        from display.screen_manager import DisplayMode
        manager = self._make_manager()
        run_async(manager.start())
        run_async(manager.set_mode(DisplayMode.DASHBOARD))
        self.assertEqual(manager._current_mode, DisplayMode.DASHBOARD)
        run_async(manager.stop())

    def test_set_mode_same_mode_is_noop(self):
        """set_mode() with the current mode should not call _notify_frontend."""
        from display.screen_manager import DisplayMode
        manager = self._make_manager()
        run_async(manager.start())
        # Already in AMBIENT
        run_async(manager.set_mode(DisplayMode.AMBIENT))
        manager._notify_frontend.assert_not_called()
        run_async(manager.stop())

    def test_brightness_clamped(self):
        """set_brightness() should clamp to [SCREEN_BRIGHTNESS_MIN, SCREEN_BRIGHTNESS_MAX]."""
        from core.constants import SCREEN_BRIGHTNESS_MAX, SCREEN_BRIGHTNESS_MIN
        manager = self._make_manager()
        manager.set_brightness(-100)
        self.assertEqual(manager.get_brightness(), SCREEN_BRIGHTNESS_MIN)
        manager.set_brightness(9999)
        self.assertEqual(manager.get_brightness(), SCREEN_BRIGHTNESS_MAX)

    def test_stop_cancels_idle_timer(self):
        """stop() should cancel the idle timer task without raising."""
        manager = self._make_manager()
        run_async(manager.start())
        try:
            run_async(manager.stop())
        except Exception as exc:
            self.fail(f"stop() raised: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# AmbientMode tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAmbientMode(unittest.TestCase):
    """Tests for display/ambient_mode.py — AmbientMode."""

    def test_get_state_returns_dict(self):
        """get_state() should return a dict with expected keys."""
        from display.ambient_mode import AmbientMode
        mode = AmbientMode()
        state = mode.get_state()
        self.assertIn("time", state)
        self.assertIn("date", state)
        self.assertIn("weather", state)
        self.assertIn("notifications", state)

    def test_add_notification_appends(self):
        """add_notification() should add to the notifications list."""
        from display.ambient_mode import AmbientMode
        mode = AmbientMode()
        mode.add_notification({"id": "n1", "title": "Test", "message": "Hello"})
        self.assertEqual(len(mode.get_state()["notifications"]), 1)

    def test_dismiss_notification_removes(self):
        """dismiss_notification() should remove the notification by id."""
        from display.ambient_mode import AmbientMode
        mode = AmbientMode()
        mode.add_notification({"id": "n1", "title": "Test", "message": "Hello"})
        mode.dismiss_notification("n1")
        self.assertEqual(len(mode.get_state()["notifications"]), 0)

    def test_notifications_capped_at_max(self):
        """Notifications list should not exceed MAX_NOTIFICATIONS_DISPLAYED."""
        from display.ambient_mode import AmbientMode
        from core.constants import MAX_NOTIFICATIONS_DISPLAYED
        mode = AmbientMode()
        for i in range(MAX_NOTIFICATIONS_DISPLAYED + 5):
            mode.add_notification({"id": str(i), "title": f"N{i}", "message": ""})
        self.assertLessEqual(
            len(mode.get_state()["notifications"]),
            MAX_NOTIFICATIONS_DISPLAYED,
        )


# ─────────────────────────────────────────────────────────────────────────────
# NotificationDisplay tests
# ─────────────────────────────────────────────────────────────────────────────

class TestNotificationDisplay(unittest.TestCase):
    """Tests for display/notification_display.py — NotificationDisplay."""

    def _make_display(self):
        from display.notification_display import NotificationDisplay
        return NotificationDisplay()

    def test_push_returns_id(self):
        """push() should return the notification's id string."""
        from display.notification_display import Notification, NotificationPriority
        nd = self._make_display()
        n = Notification(title="Test", message="Hello", priority=NotificationPriority.NORMAL)
        result_id = nd.push(n)
        self.assertEqual(result_id, n.id)

    def test_push_adds_to_active(self):
        """push() should add the notification to get_active()."""
        from display.notification_display import Notification
        nd = self._make_display()
        n = Notification(title="Alert", message="Something happened")
        nd.push(n)
        active = nd.get_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["title"], "Alert")

    def test_dismiss_removes_notification(self):
        """dismiss() should remove the notification from get_active()."""
        from display.notification_display import Notification
        nd = self._make_display()
        n = Notification(title="Temp", message="Temp message")
        nd.push(n)
        nd.dismiss(n.id)
        self.assertEqual(len(nd.get_active()), 0)

    def test_high_priority_sorted_first(self):
        """High priority notifications should appear before low priority ones."""
        from display.notification_display import Notification, NotificationPriority
        nd = self._make_display()
        low = Notification(title="Low", message="", priority=NotificationPriority.LOW)
        high = Notification(title="High", message="", priority=NotificationPriority.HIGH)
        nd.push(low)
        nd.push(high)
        active = nd.get_active()
        self.assertEqual(active[0]["title"], "High")

    def test_clear_all_empties_queue(self):
        """clear_all() should remove all active notifications."""
        from display.notification_display import Notification
        nd = self._make_display()
        for i in range(3):
            nd.push(Notification(title=f"N{i}", message=""))
        nd.clear_all()
        self.assertEqual(len(nd.get_active()), 0)


# ─────────────────────────────────────────────────────────────────────────────
# CameraViewer tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCameraViewer(unittest.TestCase):
    """Tests for display/camera_viewer.py — CameraViewer."""

    def test_get_cameras_returns_empty_without_ha(self):
        """get_cameras() should return [] when ha_client is None."""
        from display.camera_viewer import CameraViewer
        viewer = CameraViewer(ha_client=None)
        result = run_async(viewer.get_cameras())
        self.assertEqual(result, [])

    def test_get_cameras_returns_empty_when_disconnected(self):
        """get_cameras() should return [] when HA is not connected."""
        from display.camera_viewer import CameraViewer
        mock_ha = MagicMock()
        mock_ha.is_connected = False
        viewer = CameraViewer(ha_client=mock_ha)
        result = run_async(viewer.get_cameras())
        self.assertEqual(result, [])

    def test_snapshot_url_format(self):
        """_snapshot_url() should return the expected local proxy path."""
        from display.camera_viewer import CameraViewer
        viewer = CameraViewer()
        url = viewer._snapshot_url("camera.front_door")
        self.assertEqual(url, "/api/cameras/camera.front_door/snapshot")

    def test_stream_url_format(self):
        """_stream_url() should return the expected local proxy path."""
        from display.camera_viewer import CameraViewer
        viewer = CameraViewer()
        url = viewer._stream_url("camera.backyard")
        self.assertEqual(url, "/api/cameras/camera.backyard/stream")


if __name__ == "__main__":
    unittest.main()
