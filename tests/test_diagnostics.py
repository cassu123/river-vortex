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
import unittest.mock
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


class TestUnpairedIdentity(unittest.TestCase):
    """A unit in its box must not claim to be in a room."""

    def test_unpaired_config_check_names_no_room(self):
        from core.config import config
        with patch.object(config, "get", side_effect=lambda k, d=None: {
            "unit_id": "vortex-abc123", "configured": False,
            "unit_name": "", "location": "",
        }.get(k, d)), patch.object(config, "is_loaded", return_value=True):
            status, detail = Diagnostics()._check_config()
        self.assertEqual(status, CheckStatus.WARN)
        self.assertIn("unpaired", detail)
        # The whole point: no room name anywhere in that line.
        self.assertNotIn("Kitchen", detail)
        self.assertNotIn("@", detail)

    def test_paired_config_check_reports_name_and_room(self):
        from core.config import config
        with patch.object(config, "get", side_effect=lambda k, d=None: {
            "unit_id": "vortex-abc123", "configured": True,
            "unit_name": "Kitchen Vortex", "location": "Kitchen",
        }.get(k, d)), patch.object(config, "is_loaded", return_value=True):
            status, detail = Diagnostics()._check_config()
        self.assertEqual(status, CheckStatus.OK)
        self.assertIn("Kitchen Vortex", detail)


class TestShippedProfile(unittest.TestCase):
    """The image that gets flashed onto every unit."""

    def test_shipped_profile_carries_no_identity(self):
        import json, pathlib
        profile = json.loads(pathlib.Path("units/vortex_profile.json").read_text())
        for key in ("unit_id", "unit_name", "location"):
            self.assertNotIn(key, profile,
                             f"{key} must not be baked into the shipped image")

    def test_shipped_profile_is_unconfigured(self):
        import json, pathlib
        profile = json.loads(pathlib.Path("units/vortex_profile.json").read_text())
        self.assertFalse(profile.get("configured", False))


class TestDerivedUnitId(unittest.TestCase):
    """Units flashed from one image must not collide."""

    def test_pi_serial_is_preferred(self):
        from core.config import _derive_unit_id
        cpuinfo = "processor\t: 0\nSerial\t\t: 100000001a2b3c4d\n"
        with patch("builtins.open", unittest.mock.mock_open(read_data=cpuinfo)):
            unit_id = _derive_unit_id()
        self.assertTrue(unit_id.startswith("vortex-"))
        self.assertIn("1a2b3c4d", unit_id)

    def test_an_id_is_always_produced(self):
        from core.config import _derive_unit_id
        self.assertTrue(_derive_unit_id().startswith("vortex-"))

    def test_the_id_is_stable_across_calls(self):
        """It identifies the board, so it must not change between reboots."""
        from core.config import _derive_unit_id
        self.assertEqual(_derive_unit_id(), _derive_unit_id())


if __name__ == "__main__":
    unittest.main()
