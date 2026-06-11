"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/ws_hub.py
Purpose:     Lightweight WebSocket connection registry. Subsystems broadcast
             JSON event messages (display mode changes, timer updates, guided
             routine steps, etc.) to every connected frontend client through
             this shared hub. The /api/ws endpoint (see core/main.py) is the
             only place clients connect; everything else just calls
             ws_hub.broadcast(...).
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-11
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import logging
from typing import Any, Dict, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Tracks connected WebSocket clients and broadcasts JSON messages to all of them.

    Usage:
        await ws_hub.connect(websocket)   # in the /api/ws endpoint
        await ws_hub.broadcast({"type": "timers_update", "timers": [...]})
        await ws_hub.disconnect(websocket)
    """

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection and register it for broadcasts."""
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.debug("WebSocket client connected (%d total).", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection (no-op if already removed)."""
        async with self._lock:
            self._connections.discard(websocket)
        logger.debug("WebSocket client disconnected (%d total).", len(self._connections))

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """
        Send a JSON message to every connected client.

        Connections that fail to receive the message (e.g., already closed)
        are dropped silently.

        Args:
            message: JSON-serializable dict. Must include a "type" key —
                     see frontend/src/App.jsx's handleMessage() for the
                     recognized message types.
        """
        async with self._lock:
            connections = list(self._connections)

        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception:  # pylint: disable=broad-except
                await self.disconnect(websocket)

    @property
    def connection_count(self) -> int:
        """Return the number of currently connected clients."""
        return len(self._connections)


# Module-level singleton — imported by every subsystem that broadcasts events.
ws_hub = ConnectionManager()
