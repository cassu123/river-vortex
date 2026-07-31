"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_lists.py
Purpose:     Unit tests for shopping/to-do lists and upcoming reminders —
             ListsStore (core/lists.py) and the /api/vortex/v1/lists +
             /api/vortex/v1/reminders REST APIs (core/lists_api.py).
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-12
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def run_async(coro):
    """Run an async coroutine synchronously in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


SAMPLE_LISTS = [
    {
        "id": "shopping",
        "name": "Shopping",
        "items": [
            {"id": "item-1", "text": "Milk", "checked": False},
            {"id": "item-2", "text": "Eggs", "checked": True},
        ],
    },
]

SAMPLE_REMINDERS = [
    {"id": "r1", "text": "Take out the trash", "due": "2026-06-12T20:00:00"},
]


# ─────────────────────────────────────────────────────────────────────────────
# ListsStore
# ─────────────────────────────────────────────────────────────────────────────

class TestListsStore(unittest.TestCase):
    """Tests for core/lists.py — ListsStore."""

    def setUp(self):
        patcher = patch("core.ws_hub.ws_hub.broadcast", new_callable=AsyncMock)
        self.mock_broadcast = patcher.start()
        self.addCleanup(patcher.stop)

    def _make_store(self):
        from core.lists import ListsStore
        return ListsStore()

    def test_get_lists_empty_by_default(self):
        store = self._make_store()
        self.assertEqual(store.get_lists(), [])

    def test_set_lists_caches_and_broadcasts(self):
        store = self._make_store()
        result = run_async(store.set_lists(SAMPLE_LISTS))
        self.assertEqual(result, SAMPLE_LISTS)
        self.assertEqual(store.get_lists(), SAMPLE_LISTS)
        self.mock_broadcast.assert_any_call({"type": "lists_update", "lists": SAMPLE_LISTS})

    def test_toggle_item_flips_checked(self):
        store = self._make_store()
        run_async(store.set_lists(SAMPLE_LISTS))
        updated = run_async(store.toggle_item("shopping", "item-1"))
        item = next(i for i in updated["items"] if i["id"] == "item-1")
        self.assertTrue(item["checked"])

        updated = run_async(store.toggle_item("shopping", "item-1"))
        item = next(i for i in updated["items"] if i["id"] == "item-1")
        self.assertFalse(item["checked"])

    def test_toggle_item_broadcasts_update(self):
        store = self._make_store()
        run_async(store.set_lists(SAMPLE_LISTS))
        run_async(store.toggle_item("shopping", "item-1"))
        self.mock_broadcast.assert_any_call({"type": "lists_update", "lists": store.get_lists()})

    def test_toggle_item_unknown_list_raises(self):
        from core.lists import ListsError
        store = self._make_store()
        run_async(store.set_lists(SAMPLE_LISTS))
        with self.assertRaises(ListsError):
            run_async(store.toggle_item("nonexistent", "item-1"))

    def test_toggle_item_unknown_item_raises(self):
        from core.lists import ListsError
        store = self._make_store()
        run_async(store.set_lists(SAMPLE_LISTS))
        with self.assertRaises(ListsError):
            run_async(store.toggle_item("shopping", "nonexistent"))

    def test_get_reminders_empty_by_default(self):
        store = self._make_store()
        self.assertEqual(store.get_reminders(), [])

    def test_set_reminders_caches_and_broadcasts(self):
        store = self._make_store()
        result = run_async(store.set_reminders(SAMPLE_REMINDERS))
        self.assertEqual(result, SAMPLE_REMINDERS)
        self.assertEqual(store.get_reminders(), SAMPLE_REMINDERS)
        self.mock_broadcast.assert_any_call(
            {"type": "reminders_update", "reminders": SAMPLE_REMINDERS}
        )


# ─────────────────────────────────────────────────────────────────────────────
# /api/vortex/v1/lists and /api/vortex/v1/reminders
# ─────────────────────────────────────────────────────────────────────────────

class TestListsAPI(unittest.TestCase):
    """Tests for core/lists_api.py — /api/vortex/v1/lists and /reminders routes."""

    def setUp(self):
        patcher = patch("core.ws_hub.ws_hub.broadcast", new_callable=AsyncMock)
        self.mock_broadcast = patcher.start()
        self.addCleanup(patcher.stop)

        from core.lists import ListsStore
        from core.lists_api import reminders_router, router, set_lists_store

        self.store = ListsStore()
        set_lists_store(self.store)
        self.addCleanup(set_lists_store, None)

        app = FastAPI()
        app.include_router(router)
        app.include_router(reminders_router)
        self.client = TestClient(app)

    def test_get_lists_empty(self):
        resp = self.client.get("/api/vortex/v1/lists")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"lists": []})

    def test_set_lists_returns_snapshot(self):
        resp = self.client.post("/api/vortex/v1/lists", json={"lists": SAMPLE_LISTS})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["lists"]), 1)
        self.assertEqual(data["lists"][0]["id"], "shopping")
        self.assertEqual(len(data["lists"][0]["items"]), 2)

    def test_set_lists_requires_valid_shape(self):
        resp = self.client.post("/api/vortex/v1/lists", json={"lists": [{"id": "x"}]})
        self.assertEqual(resp.status_code, 422)

    def test_toggle_item_returns_updated_list(self):
        self.client.post("/api/vortex/v1/lists", json={"lists": SAMPLE_LISTS})
        resp = self.client.post("/api/vortex/v1/lists/shopping/items/item-1/toggle")
        self.assertEqual(resp.status_code, 200)
        item = next(i for i in resp.json()["items"] if i["id"] == "item-1")
        self.assertTrue(item["checked"])

    def test_toggle_item_unknown_list_returns_404(self):
        self.client.post("/api/vortex/v1/lists", json={"lists": SAMPLE_LISTS})
        resp = self.client.post("/api/vortex/v1/lists/nonexistent/items/item-1/toggle")
        self.assertEqual(resp.status_code, 404)

    def test_toggle_item_unknown_item_returns_404(self):
        self.client.post("/api/vortex/v1/lists", json={"lists": SAMPLE_LISTS})
        resp = self.client.post("/api/vortex/v1/lists/shopping/items/nonexistent/toggle")
        self.assertEqual(resp.status_code, 404)

    def test_get_reminders_empty(self):
        resp = self.client.get("/api/vortex/v1/reminders")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"reminders": []})

    def test_set_reminders_returns_snapshot(self):
        resp = self.client.post("/api/vortex/v1/reminders", json={"reminders": SAMPLE_REMINDERS})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data["reminders"]), 1)
        self.assertEqual(data["reminders"][0]["text"], "Take out the trash")

    def test_set_reminders_requires_valid_shape(self):
        resp = self.client.post("/api/vortex/v1/reminders", json={"reminders": [{"id": "r1"}]})
        self.assertEqual(resp.status_code, 422)


class TestListsAPIUnavailable(unittest.TestCase):
    """The /lists and /reminders routes should respond 503 when no store is wired."""

    def setUp(self):
        from core.lists_api import reminders_router, router, set_lists_store
        set_lists_store(None)
        self.addCleanup(set_lists_store, None)

        app = FastAPI()
        app.include_router(router)
        app.include_router(reminders_router)
        self.client = TestClient(app)

    def test_get_lists_503_without_store(self):
        resp = self.client.get("/api/vortex/v1/lists")
        self.assertEqual(resp.status_code, 503)

    def test_set_lists_503_without_store(self):
        resp = self.client.post("/api/vortex/v1/lists", json={"lists": []})
        self.assertEqual(resp.status_code, 503)

    def test_toggle_item_503_without_store(self):
        resp = self.client.post("/api/vortex/v1/lists/shopping/items/item-1/toggle")
        self.assertEqual(resp.status_code, 503)

    def test_get_reminders_503_without_store(self):
        resp = self.client.get("/api/vortex/v1/reminders")
        self.assertEqual(resp.status_code, 503)

    def test_set_reminders_503_without_store(self):
        resp = self.client.post("/api/vortex/v1/reminders", json={"reminders": []})
        self.assertEqual(resp.status_code, 503)


if __name__ == "__main__":
    unittest.main()
