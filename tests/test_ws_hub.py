"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_ws_hub.py
Purpose:     Unit tests for the shared WebSocket broadcast hub
             (core/ws_hub.py) — connection registry and broadcast fan-out.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-11
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from fastapi import WebSocket


def run_async(coro):
    """Run an async coroutine synchronously in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestConnectionManager(unittest.TestCase):
    """Tests for core/ws_hub.py — ConnectionManager."""

    def _make_manager(self):
        from core.ws_hub import ConnectionManager
        return ConnectionManager()

    def _make_ws(self):
        ws = MagicMock(spec=WebSocket)
        ws.accept = AsyncMock()
        ws.send_json = AsyncMock()
        return ws

    def test_connection_count_starts_at_zero(self):
        manager = self._make_manager()
        self.assertEqual(manager.connection_count, 0)

    def test_connect_accepts_and_registers(self):
        manager = self._make_manager()
        ws = self._make_ws()
        run_async(manager.connect(ws))
        ws.accept.assert_awaited_once()
        self.assertEqual(manager.connection_count, 1)

    def test_disconnect_removes_connection(self):
        manager = self._make_manager()
        ws = self._make_ws()
        run_async(manager.connect(ws))
        run_async(manager.disconnect(ws))
        self.assertEqual(manager.connection_count, 0)

    def test_disconnect_unknown_connection_is_noop(self):
        manager = self._make_manager()
        ws = self._make_ws()
        try:
            run_async(manager.disconnect(ws))
        except Exception as exc:
            self.fail(f"disconnect() raised unexpectedly: {exc}")

    def test_broadcast_sends_to_all_connections(self):
        manager = self._make_manager()
        ws1, ws2 = self._make_ws(), self._make_ws()
        run_async(manager.connect(ws1))
        run_async(manager.connect(ws2))

        message = {"type": "timers_update", "timers": []}
        run_async(manager.broadcast(message))

        ws1.send_json.assert_awaited_once_with(message)
        ws2.send_json.assert_awaited_once_with(message)

    def test_broadcast_drops_failed_connections(self):
        manager = self._make_manager()
        ws_good, ws_bad = self._make_ws(), self._make_ws()
        ws_bad.send_json = AsyncMock(side_effect=RuntimeError("connection closed"))

        run_async(manager.connect(ws_good))
        run_async(manager.connect(ws_bad))
        run_async(manager.broadcast({"type": "ping"}))

        self.assertEqual(manager.connection_count, 1)

    def test_broadcast_with_no_connections_is_noop(self):
        manager = self._make_manager()
        try:
            run_async(manager.broadcast({"type": "ping"}))
        except Exception as exc:
            self.fail(f"broadcast() raised unexpectedly: {exc}")


if __name__ == "__main__":
    unittest.main()
