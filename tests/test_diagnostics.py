"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_diagnostics.py
Purpose:     Tests for core/diagnostics.py — the boot self-test.

             The point of these checks is that they can genuinely fail, so
             what is tested here is that failures are reported rather than
             swallowed, and that a broken check never takes the boot screen
             down with it.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import unittest
from unittest.mock import patch

from core.diagnostics import CheckStatus, Diagnostics


def run_async(coro):
    """Run a coroutine on the suite's shared event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestRun(unittest.TestCase):
    """Running the full self-test."""

    def test_every_check_produces_a_result(self):
        diagnostics = Diagnostics()
        results = run_async(diagnostics.run())
        self.assertEqual(len(results), len(diagnostics._checks()))
        for result in results:
            self.assertIn(result["status"],
                          {CheckStatus.OK, CheckStatus.WARN,
                           CheckStatus.FAIL, CheckStatus.SKIP})
            self.assertTrue(result["label"])
            self.assertIsInstance(result["elapsed_ms"], int)

    def test_report_is_marked_complete_and_counted(self):
        diagnostics = Diagnostics()
        run_async(diagnostics.run())
        report = diagnostics.get_report()
        self.assertTrue(report["complete"])
        self.assertEqual(sum(report["counts"].values()), len(report["results"]))

    def test_results_stream_as_each_check_finishes(self):
        """The boot screen fills in progressively, so timing must be real."""
        seen = []

        async def on_result(result, report):
            if result is not None:
                seen.append(result["label"])

        diagnostics = Diagnostics(on_result=on_result)
        results = run_async(diagnostics.run())
        self.assertEqual(seen, [r["label"] for r in results])

    def test_a_completion_sentinel_is_emitted_last(self):
        emitted = []

        async def on_result(result, report):
            emitted.append(result)

        run_async(Diagnostics(on_result=on_result).run())
        self.assertIsNone(emitted[-1])

    def test_report_before_running_is_empty_but_valid(self):
        """The boot screen may fetch before anything has run."""
        report = Diagnostics().get_report()
        self.assertEqual(report["results"], [])
        self.assertFalse(report["complete"])


class TestFailureHandling(unittest.TestCase):
    """A check that explodes must not take the boot screen with it."""

    def test_a_raising_check_is_recorded_as_a_failure(self):
        diagnostics = Diagnostics()

        def boom():
            raise RuntimeError("sensor on fire")

        with patch.object(Diagnostics, "_checks",
                          return_value=[("EXPLODING", boom)]):
            results = run_async(diagnostics.run())

        self.assertEqual(results[0]["status"], CheckStatus.FAIL)
        self.assertIn("sensor on fire", results[0]["detail"])

    def test_the_run_continues_past_a_failing_check(self):
        diagnostics = Diagnostics()

        def boom():
            raise RuntimeError("nope")

        def fine():
            return CheckStatus.OK, "still here"

        with patch.object(Diagnostics, "_checks",
                          return_value=[("BAD", boom), ("GOOD", fine)]):
            results = run_async(diagnostics.run())

        self.assertEqual(len(results), 2)
        self.assertEqual(results[1]["status"], CheckStatus.OK)

    def test_a_failing_listener_does_not_stop_the_run(self):
        async def on_result(result, report):
            raise RuntimeError("websocket died")

        diagnostics = Diagnostics(on_result=on_result)
        with patch.object(Diagnostics, "_checks",
                          return_value=[("X", lambda: (CheckStatus.OK, "ok"))]):
            results = run_async(diagnostics.run())
        self.assertEqual(len(results), 1)

    def test_healthy_is_false_when_something_failed(self):
        diagnostics = Diagnostics()
        with patch.object(Diagnostics, "_checks",
                          return_value=[("X", lambda: (CheckStatus.FAIL, "broken"))]):
            run_async(diagnostics.run())
        self.assertFalse(diagnostics.get_report()["healthy"])

    def test_warnings_alone_do_not_make_a_unit_unhealthy(self):
        """A warning is degraded, not broken — the unit still boots."""
        diagnostics = Diagnostics()
        with patch.object(Diagnostics, "_checks",
                          return_value=[("X", lambda: (CheckStatus.WARN, "meh"))]):
            run_async(diagnostics.run())
        self.assertTrue(diagnostics.get_report()["healthy"])


class TestIndividualChecks(unittest.TestCase):
    """Spot-checks that the real probes report real state."""

    def test_storage_reports_actual_free_space(self):
        status, detail = Diagnostics()._check_storage()
        self.assertIn("GB free", detail)
        self.assertIn(status, {CheckStatus.OK, CheckStatus.WARN, CheckStatus.FAIL})

    def test_storage_fails_when_the_disk_is_nearly_full(self):
        import collections
        usage = collections.namedtuple("usage", "total used free")
        with patch("shutil.disk_usage", return_value=usage(100, 99, 100 * 1024)):
            status, _ = Diagnostics()._check_storage()
        self.assertEqual(status, CheckStatus.FAIL)

    def test_media_engine_reflects_whether_mpv_is_installed(self):
        with patch("shutil.which", return_value=None):
            status, detail = Diagnostics()._check_media()
        self.assertEqual(status, CheckStatus.WARN)
        self.assertIn("mpv", detail)

    def test_runtime_check_always_passes(self):
        """If this fails, nothing else could have run to report it."""
        status, _ = Diagnostics()._check_runtime()
        self.assertEqual(status, CheckStatus.OK)


if __name__ == "__main__":
    unittest.main()
