"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_routines.py
Purpose:     Unit tests for guided routine sessions (cooking mode, etc.) —
             RoutineSession (core/routines.py) and the
             /api/vortex/v1/routine REST API (core/routines_api.py),
             including media ducking via DeviceControl and display mode
             switching.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-11
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, call, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def run_async(coro):
    """Run an async coroutine synchronously in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


SIMPLE_STEPS = [{"instruction": "Boil water."}, {"instruction": "Add pasta.", "duration_seconds": 540}]


# ─────────────────────────────────────────────────────────────────────────────
# RoutineSession
# ─────────────────────────────────────────────────────────────────────────────

class TestRoutineSession(unittest.TestCase):
    """Tests for core/routines.py — RoutineSession."""

    def setUp(self):
        patcher = patch("core.ws_hub.ws_hub.broadcast", new_callable=AsyncMock)
        self.mock_broadcast = patcher.start()
        self.addCleanup(patcher.stop)

    def _make_session(self, device_control=None, on_mode_change=None):
        from core.routines import RoutineSession
        return RoutineSession(device_control=device_control, on_mode_change=on_mode_change)

    def _make_device_control(self, players=None):
        dc = MagicMock()
        dc.get_all_media_players = AsyncMock(return_value=players or [])
        dc.set_media_volume = AsyncMock(return_value=True)
        return dc

    def test_get_state_before_start(self):
        session = self._make_session()
        self.assertEqual(session.get_state(), {"active": False})
        self.assertFalse(session.active)

    def test_start_requires_at_least_one_step(self):
        from core.routines import RoutineError
        session = self._make_session()
        with self.assertRaises(RoutineError):
            run_async(session.start("Empty", []))

    def test_start_sets_active_state(self):
        session = self._make_session()
        state = run_async(session.start("Spaghetti", SIMPLE_STEPS))
        self.assertTrue(state["active"])
        self.assertTrue(session.active)
        self.assertEqual(state["title"], "Spaghetti")
        self.assertEqual(state["step_index"], 0)
        self.assertEqual(state["step_count"], 2)
        self.assertEqual(state["step"], SIMPLE_STEPS[0])
        self.assertFalse(state["is_last_step"])

    def test_next_step_advances_index(self):
        session = self._make_session()
        run_async(session.start("Spaghetti", SIMPLE_STEPS))
        state = run_async(session.next_step())
        self.assertEqual(state["step_index"], 1)
        self.assertTrue(state["is_last_step"])
        self.assertTrue(state["active"])

    def test_next_step_on_last_step_stops_routine(self):
        session = self._make_session()
        run_async(session.start("Single Step", [{"instruction": "Done"}]))
        state = run_async(session.next_step())
        self.assertFalse(state["active"])

    def test_next_step_without_active_routine_raises(self):
        from core.routines import RoutineError
        session = self._make_session()
        with self.assertRaises(RoutineError):
            run_async(session.next_step())

    def test_previous_step_noop_on_first_step(self):
        session = self._make_session()
        run_async(session.start("Spaghetti", SIMPLE_STEPS))
        state = run_async(session.previous_step())
        self.assertEqual(state["step_index"], 0)

    def test_previous_step_goes_back(self):
        session = self._make_session()
        run_async(session.start("Spaghetti", SIMPLE_STEPS))
        run_async(session.next_step())
        state = run_async(session.previous_step())
        self.assertEqual(state["step_index"], 0)

    def test_previous_step_without_active_routine_raises(self):
        from core.routines import RoutineError
        session = self._make_session()
        with self.assertRaises(RoutineError):
            run_async(session.previous_step())

    def test_stop_without_active_routine_raises(self):
        from core.routines import RoutineError
        session = self._make_session()
        with self.assertRaises(RoutineError):
            run_async(session.stop())

    def test_stop_marks_inactive(self):
        session = self._make_session()
        run_async(session.start("Spaghetti", SIMPLE_STEPS))
        state = run_async(session.stop())
        self.assertFalse(state["active"])
        self.assertFalse(session.active)
        self.assertEqual(state["title"], "Spaghetti")

    def test_broadcast_called_on_start(self):
        session = self._make_session()
        run_async(session.start("Spaghetti", SIMPLE_STEPS))
        self.mock_broadcast.assert_called_with(
            {"type": "routine_update", "routine": session.get_state()}
        )

    # ── Display mode switching ──────────────────────────────────────────────

    def test_set_mode_called_on_start_and_stop(self):
        on_mode_change = AsyncMock()
        session = self._make_session(on_mode_change=on_mode_change)
        run_async(session.start("Spaghetti", SIMPLE_STEPS))
        on_mode_change.assert_called_with("routine")
        run_async(session.stop())
        on_mode_change.assert_called_with("ambient")

    def test_set_mode_failure_does_not_raise(self):
        on_mode_change = AsyncMock(side_effect=RuntimeError("display offline"))
        session = self._make_session(on_mode_change=on_mode_change)
        try:
            run_async(session.start("Spaghetti", SIMPLE_STEPS))
        except Exception as exc:
            self.fail(f"start() raised unexpectedly: {exc}")

    def test_no_mode_change_callback_is_safe(self):
        session = self._make_session(on_mode_change=None)
        try:
            run_async(session.start("Spaghetti", SIMPLE_STEPS))
            run_async(session.stop())
        except Exception as exc:
            self.fail(f"Routine lifecycle raised unexpectedly: {exc}")

    # ── Media ducking ────────────────────────────────────────────────────────

    def test_start_ducks_only_playing_media_players(self):
        from core.constants import ROUTINE_DUCK_VOLUME_LEVEL
        dc = self._make_device_control(players=[
            {"entity_id": "media_player.living_room", "state": "playing", "attributes": {"volume_level": 0.6}},
            {"entity_id": "media_player.bedroom", "state": "paused", "attributes": {"volume_level": 0.5}},
        ])
        session = self._make_session(device_control=dc)
        run_async(session.start("Spaghetti", SIMPLE_STEPS))
        dc.set_media_volume.assert_called_once_with("media_player.living_room", ROUTINE_DUCK_VOLUME_LEVEL)

    def test_stop_restores_ducked_media_volume(self):
        dc = self._make_device_control(players=[
            {"entity_id": "media_player.living_room", "state": "playing", "attributes": {"volume_level": 0.6}},
        ])
        session = self._make_session(device_control=dc)
        run_async(session.start("Spaghetti", SIMPLE_STEPS))
        run_async(session.stop())
        dc.set_media_volume.assert_called_with("media_player.living_room", 0.6)

    def test_no_device_control_skips_ducking(self):
        session = self._make_session(device_control=None)
        try:
            run_async(session.start("Spaghetti", SIMPLE_STEPS))
            run_async(session.stop())
        except Exception as exc:
            self.fail(f"Routine lifecycle raised unexpectedly: {exc}")

    def test_get_all_media_players_error_is_handled(self):
        dc = self._make_device_control()
        dc.get_all_media_players = AsyncMock(side_effect=RuntimeError("HA unreachable"))
        session = self._make_session(device_control=dc)
        try:
            run_async(session.start("Spaghetti", SIMPLE_STEPS))
        except Exception as exc:
            self.fail(f"start() raised unexpectedly: {exc}")

    def test_replacing_active_routine_restores_previous_media(self):
        dc = self._make_device_control(players=[
            {"entity_id": "media_player.kitchen", "state": "playing", "attributes": {"volume_level": 0.8}},
        ])
        session = self._make_session(device_control=dc)
        run_async(session.start("First", [{"instruction": "A"}]))
        run_async(session.start("Second", [{"instruction": "B"}]))

        self.assertIn(call("media_player.kitchen", 0.8), dc.set_media_volume.call_args_list)
        self.assertEqual(session.get_state()["title"], "Second")


# ─────────────────────────────────────────────────────────────────────────────
# /api/vortex/v1/routine
# ─────────────────────────────────────────────────────────────────────────────

class TestRoutinesAPI(unittest.TestCase):
    """Tests for core/routines_api.py — /api/vortex/v1/routine routes."""

    def setUp(self):
        patcher = patch("core.ws_hub.ws_hub.broadcast", new_callable=AsyncMock)
        self.mock_broadcast = patcher.start()
        self.addCleanup(patcher.stop)

        from core.routines import RoutineSession
        from core.routines_api import router, set_routine_session

        self.session = RoutineSession()
        set_routine_session(self.session)
        self.addCleanup(set_routine_session, None)

        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_get_routine_inactive(self):
        resp = self.client.get("/api/vortex/v1/routine")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"active": False})

    def test_start_routine_returns_201(self):
        resp = self.client.post(
            "/api/vortex/v1/routine",
            json={"title": "Spaghetti Carbonara", "steps": SIMPLE_STEPS},
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data["active"])
        self.assertEqual(data["title"], "Spaghetti Carbonara")
        self.assertEqual(data["step_count"], 2)
        self.assertEqual(data["step"]["instruction"], "Boil water.")

    def test_start_routine_requires_steps(self):
        resp = self.client.post("/api/vortex/v1/routine", json={"title": "Empty", "steps": []})
        self.assertEqual(resp.status_code, 422)

    def test_start_routine_requires_title(self):
        resp = self.client.post("/api/vortex/v1/routine", json={"title": "", "steps": SIMPLE_STEPS})
        self.assertEqual(resp.status_code, 422)

    def test_next_and_previous_step(self):
        self.client.post("/api/vortex/v1/routine", json={"title": "R", "steps": SIMPLE_STEPS})

        resp = self.client.post("/api/vortex/v1/routine/next")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["step_index"], 1)

        resp = self.client.post("/api/vortex/v1/routine/previous")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["step_index"], 0)

    def test_next_step_without_active_routine_returns_409(self):
        resp = self.client.post("/api/vortex/v1/routine/next")
        self.assertEqual(resp.status_code, 409)

    def test_previous_step_without_active_routine_returns_409(self):
        resp = self.client.post("/api/vortex/v1/routine/previous")
        self.assertEqual(resp.status_code, 409)

    def test_stop_routine(self):
        self.client.post("/api/vortex/v1/routine", json={"title": "R", "steps": SIMPLE_STEPS})
        resp = self.client.delete("/api/vortex/v1/routine")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["active"])

    def test_stop_without_active_routine_returns_409(self):
        resp = self.client.delete("/api/vortex/v1/routine")
        self.assertEqual(resp.status_code, 409)

    def test_starting_new_routine_replaces_active_one(self):
        self.client.post("/api/vortex/v1/routine", json={"title": "First", "steps": SIMPLE_STEPS})
        resp = self.client.post("/api/vortex/v1/routine", json={"title": "Second", "steps": SIMPLE_STEPS})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["title"], "Second")


class TestRoutinesAPIUnavailable(unittest.TestCase):
    """The /routine routes should respond 503 when no RoutineSession is wired."""

    def setUp(self):
        from core.routines_api import router, set_routine_session
        set_routine_session(None)
        self.addCleanup(set_routine_session, None)

        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_get_routine_503_without_session(self):
        resp = self.client.get("/api/vortex/v1/routine")
        self.assertEqual(resp.status_code, 503)

    def test_start_routine_503_without_session(self):
        resp = self.client.post(
            "/api/vortex/v1/routine", json={"title": "R", "steps": SIMPLE_STEPS}
        )
        self.assertEqual(resp.status_code, 503)


if __name__ == "__main__":
    unittest.main()
