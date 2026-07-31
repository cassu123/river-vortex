"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_timers.py
Purpose:     Unit tests for kitchen timers/alarms — TimerManager
             (core/timers.py) and the /api/vortex/v1/timers REST API
             (core/timers_api.py).
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-11
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def run_async(coro):
    """Run an async coroutine synchronously in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────────
# TimerManager
# ─────────────────────────────────────────────────────────────────────────────

class TestTimerManager(unittest.TestCase):
    """Tests for core/timers.py — TimerManager."""

    def setUp(self):
        patcher = patch("core.ws_hub.ws_hub.broadcast", new_callable=AsyncMock)
        self.mock_broadcast = patcher.start()
        self.addCleanup(patcher.stop)

    def test_create_timer_returns_public_dict(self):
        from core.timers import TimerManager
        manager = TimerManager()
        timer = run_async(manager.create_timer(600, "Pasta"))
        self.assertEqual(timer["label"], "Pasta")
        self.assertEqual(timer["duration_seconds"], 600)
        self.assertIn("id", timer)
        self.assertIn("remaining_seconds", timer)
        run_async(manager.stop())

    def test_create_timer_default_label(self):
        from core.timers import TimerManager
        manager = TimerManager()
        timer = run_async(manager.create_timer(60))
        self.assertEqual(timer["label"], "Timer")
        run_async(manager.stop())

    def test_create_timer_rejects_non_positive_duration(self):
        from core.timers import TimerManager
        manager = TimerManager()
        with self.assertRaises(ValueError):
            run_async(manager.create_timer(0, "Bad"))
        run_async(manager.stop())

    def test_create_timer_broadcasts_update(self):
        from core.timers import TimerManager
        manager = TimerManager()
        run_async(manager.create_timer(60, "Soup"))
        message = self.mock_broadcast.call_args[0][0]
        self.assertEqual(message["type"], "timers_update")
        self.assertEqual(len(message["timers"]), 1)
        run_async(manager.stop())

    def test_list_timers_includes_created_timer(self):
        from core.timers import TimerManager
        manager = TimerManager()
        timer = run_async(manager.create_timer(60, "Tea"))
        timers = manager.list_timers()
        self.assertEqual(len(timers), 1)
        self.assertEqual(timers[0]["id"], timer["id"])
        run_async(manager.stop())

    def test_cancel_timer_removes_it(self):
        from core.timers import TimerManager
        manager = TimerManager()
        timer = run_async(manager.create_timer(60, "Tea"))
        result = run_async(manager.cancel_timer(timer["id"]))
        self.assertTrue(result)
        self.assertEqual(manager.list_timers(), [])

    def test_cancel_unknown_timer_returns_false(self):
        from core.timers import TimerManager
        manager = TimerManager()
        result = run_async(manager.cancel_timer("doesnotexist"))
        self.assertFalse(result)

    def test_timer_elapses_fires_callback_and_broadcasts_done(self):
        from core.timers import TimerManager
        callback = MagicMock()
        manager = TimerManager(on_timer_done=callback)
        run_async(manager.create_timer(0.01, "Quick"))
        run_async(asyncio.sleep(0.1))

        callback.assert_called_once()
        self.assertEqual(callback.call_args[0][0]["label"], "Quick")
        self.assertEqual(manager.list_timers(), [])

        broadcast_types = [c.args[0]["type"] for c in self.mock_broadcast.call_args_list]
        self.assertIn("timer_done", broadcast_types)
        self.assertIn("timers_update", broadcast_types)

    def test_stop_cancels_all_timers(self):
        from core.timers import TimerManager
        manager = TimerManager()
        run_async(manager.create_timer(600, "A"))
        run_async(manager.create_timer(600, "B"))
        run_async(manager.stop())
        self.assertEqual(manager.list_timers(), [])


# ─────────────────────────────────────────────────────────────────────────────
# /api/vortex/v1/timers
# ─────────────────────────────────────────────────────────────────────────────

class TestTimersAPI(unittest.TestCase):
    """Tests for core/timers_api.py — /api/vortex/v1/timers routes."""

    def setUp(self):
        patcher = patch("core.ws_hub.ws_hub.broadcast", new_callable=AsyncMock)
        self.mock_broadcast = patcher.start()
        self.addCleanup(patcher.stop)

        from core.timers import TimerManager
        from core.timers_api import router, set_timer_manager

        self.manager = TimerManager()
        set_timer_manager(self.manager)
        self.addCleanup(set_timer_manager, None)
        self.addCleanup(run_async, self.manager.stop())

        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_list_timers_empty(self):
        resp = self.client.get("/api/vortex/v1/timers")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"timers": []})

    def test_create_timer_returns_201(self):
        resp = self.client.post(
            "/api/vortex/v1/timers", json={"duration_seconds": 600, "label": "Pasta"}
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["label"], "Pasta")
        self.assertEqual(data["duration_seconds"], 600)
        self.assertIn("id", data)

    def test_create_timer_default_label(self):
        resp = self.client.post("/api/vortex/v1/timers", json={"duration_seconds": 60})
        self.assertEqual(resp.json()["label"], "Timer")

    def test_create_timer_rejects_non_positive_duration(self):
        resp = self.client.post(
            "/api/vortex/v1/timers", json={"duration_seconds": 0, "label": "Bad"}
        )
        self.assertEqual(resp.status_code, 422)

    def test_create_timer_rejects_too_long_duration(self):
        from core.constants import MAX_TIMER_DURATION_SECONDS
        resp = self.client.post(
            "/api/vortex/v1/timers",
            json={"duration_seconds": MAX_TIMER_DURATION_SECONDS + 1},
        )
        self.assertEqual(resp.status_code, 422)

    def test_list_timers_after_create(self):
        self.client.post("/api/vortex/v1/timers", json={"duration_seconds": 600, "label": "Rice"})
        resp = self.client.get("/api/vortex/v1/timers")
        timers = resp.json()["timers"]
        self.assertEqual(len(timers), 1)
        self.assertEqual(timers[0]["label"], "Rice")

    def test_cancel_timer(self):
        create_resp = self.client.post("/api/vortex/v1/timers", json={"duration_seconds": 600})
        timer_id = create_resp.json()["id"]

        del_resp = self.client.delete(f"/api/vortex/v1/timers/{timer_id}")
        self.assertEqual(del_resp.status_code, 200)
        self.assertEqual(del_resp.json(), {"status": "cancelled"})

        resp = self.client.get("/api/vortex/v1/timers")
        self.assertEqual(resp.json(), {"timers": []})

    def test_cancel_unknown_timer_returns_404(self):
        resp = self.client.delete("/api/vortex/v1/timers/doesnotexist")
        self.assertEqual(resp.status_code, 404)


class TestTimersAPIUnavailable(unittest.TestCase):
    """The /timers routes should respond 503 when no TimerManager is wired."""

    def setUp(self):
        from core.timers_api import router, set_timer_manager
        set_timer_manager(None)
        self.addCleanup(set_timer_manager, None)

        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_list_timers_503_without_manager(self):
        resp = self.client.get("/api/vortex/v1/timers")
        self.assertEqual(resp.status_code, 503)

    def test_create_timer_503_without_manager(self):
        resp = self.client.post("/api/vortex/v1/timers", json={"duration_seconds": 60})
        self.assertEqual(resp.status_code, 503)


if __name__ == "__main__":
    unittest.main()
