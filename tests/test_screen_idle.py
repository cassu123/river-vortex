"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_screen_idle.py
Purpose:     Tests for the burn-in protection staircase in
             display/screen_manager.py.

             A wall panel shows the same layout all day, so the idle chain
             (ambient → screensaver → backlight off) is what stops a permanent
             ghost of the clock being etched into the display. These tests
             assert the stages happen in order, that waking restores power,
             and that a dark screen does not restart the chain.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from display.screen_manager import DisplayMode, ScreenManager


def run_async(coro):
    """Run a coroutine on the suite's shared event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestIdleStaircase(unittest.TestCase):
    """The ambient → screensaver → off progression."""

    def setUp(self):
        # Hardware writes and the frontend socket are both out of scope here.
        for target in ("_apply_brightness", "_set_backlight_power"):
            p = patch.object(ScreenManager, target)
            p.start()
            self.addCleanup(p.stop)
        notify = patch.object(ScreenManager, "_notify_frontend", new_callable=AsyncMock)
        self.notify = notify.start()
        self.addCleanup(notify.stop)
        # Waking restarts the idle timer, which spawns a background task. With
        # every timeout compressed to zero those tasks fire the instant the
        # loop next runs -- i.e. during the NEXT test -- polluting its mock.
        # Drain them between tests.
        self.addCleanup(self._drain_pending_tasks)

    @staticmethod
    def _drain_pending_tasks():
        """Cancel any timer tasks left running on the shared event loop."""
        loop = asyncio.get_event_loop()
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True))

    def _manager(self):
        sm = ScreenManager()
        sm._running = True
        # ScreenManager initialises to AMBIENT, and set_mode() no-ops when the
        # target equals the current mode. Start from an interactive screen so
        # the ambient step is a real transition, which is the realistic case:
        # the chain only runs after the user was actually using the panel.
        sm._current_mode = DisplayMode.DASHBOARD
        # Compress the staircase so the test does not sleep for 90 minutes.
        sm._ambient_timeout = 0
        sm._screensaver_timeout = 0
        sm._screen_off_timeout = 0
        return sm

    def test_idle_walks_all_three_stages_in_order(self):
        sm = self._manager()
        run_async(sm._idle_timeout_handler())
        modes = [call.args[0] for call in self.notify.await_args_list]
        self.assertEqual(modes, [DisplayMode.AMBIENT,
                                 DisplayMode.SCREENSAVER,
                                 DisplayMode.OFF])

    def test_screensaver_dims_rather_than_powering_off(self):
        sm = self._manager()
        run_async(sm.go_screensaver())
        self.assertEqual(sm._current_mode, DisplayMode.SCREENSAVER)
        sm._set_backlight_power.assert_called_with(True)

    def test_screen_off_cuts_the_backlight(self):
        sm = self._manager()
        run_async(sm.screen_off())
        self.assertEqual(sm._current_mode, DisplayMode.OFF)
        sm._set_backlight_power.assert_called_with(False)

    def test_off_does_not_restart_the_idle_chain(self):
        """Otherwise a dark screen would walk the whole staircase again."""
        sm = self._manager()
        with patch.object(sm, "_reset_idle_timer") as reset:
            run_async(sm.screen_off())
        reset.assert_not_called()

    def test_wake_restores_power_and_lands_on_dashboard(self):
        sm = self._manager()
        run_async(sm.screen_off())
        sm._screen_on = False
        run_async(sm.wake())
        self.assertEqual(sm._current_mode, DisplayMode.DASHBOARD)
        sm._set_backlight_power.assert_called_with(True)

    def test_wake_can_target_a_specific_mode(self):
        """A timer finishing should wake to its own screen, not the dashboard."""
        sm = self._manager()
        run_async(sm.screen_off())
        run_async(sm.wake(DisplayMode.ROUTINE))
        self.assertEqual(sm._current_mode, DisplayMode.ROUTINE)

    def test_activity_wakes_from_screensaver(self):
        sm = self._manager()
        run_async(sm.go_screensaver())

        # register_activity() schedules the wake with create_task, so it needs
        # a running loop and a tick to let the task actually execute.
        async def touch():
            with patch.object(sm, "_reset_idle_timer"):
                sm.register_activity()
            await asyncio.sleep(0)

        run_async(touch())
        self.assertEqual(sm._current_mode, DisplayMode.DASHBOARD)

    def test_activity_wakes_from_a_dark_screen(self):
        sm = self._manager()
        run_async(sm.screen_off())

        async def touch():
            with patch.object(sm, "_reset_idle_timer"):
                sm.register_activity()
            await asyncio.sleep(0)

        run_async(touch())
        self.assertEqual(sm._current_mode, DisplayMode.DASHBOARD)


class TestTimeoutOrdering(unittest.TestCase):
    """The three timeouts are measured from the last activity, so they nest."""

    def test_defaults_increase_across_stages(self):
        from core.constants import (
            AMBIENT_MODE_TIMEOUT_SECONDS,
            SCREENSAVER_TIMEOUT_SECONDS,
            SCREEN_OFF_TIMEOUT_SECONDS,
        )
        self.assertLess(AMBIENT_MODE_TIMEOUT_SECONDS, SCREENSAVER_TIMEOUT_SECONDS)
        self.assertLess(SCREENSAVER_TIMEOUT_SECONDS, SCREEN_OFF_TIMEOUT_SECONDS)


if __name__ == "__main__":
    unittest.main()
