"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/lists.py
Purpose:     Local cache for shopping/to-do lists and upcoming reminders —
             ListsStore, backing the /api/vortex/v1/lists and
             /api/vortex/v1/reminders REST APIs (core/lists_api.py).
             River Song owns persistence for lists and reminders; Vortex
             caches the latest snapshot for instant on-screen display and
             broadcasts updates over the WebSocket hub so every connected
             display stays in sync. Touch actions (checking off a list item)
             update the cache immediately for a responsive UI — River Song
             picks up the change on its next snapshot push.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-12
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import copy
import logging
from typing import Any, Dict, List

from core.ws_hub import ws_hub

logger = logging.getLogger(__name__)


class ListsError(Exception):
    """Raised when a requested list or list item does not exist."""


class ListsStore:
    """
    Caches the latest shopping/to-do list and reminder snapshots from River Song.

    Usage:
        store = ListsStore()
        await store.set_lists([{"id": "shopping", "name": "Shopping", "items": [...]}])
        await store.toggle_item("shopping", "item-1")
        await store.set_reminders([{"id": "r1", "text": "Take out the trash", "due": "..."}])
    """

    def __init__(self) -> None:
        self._lists: List[Dict[str, Any]] = []
        self._reminders: List[Dict[str, Any]] = []

    # ─────────────────────────────────────────────────────────────────────────
    # Lists
    # ─────────────────────────────────────────────────────────────────────────

    def get_lists(self) -> List[Dict[str, Any]]:
        """Return the cached list snapshot."""
        return self._lists

    async def set_lists(self, lists: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Replace the cached list snapshot (pushed by River Song) and broadcast
        `lists_update` to all connected displays.

        Args:
            lists: Full list snapshot — each item is
                   {"id", "name", "items": [{"id", "text", "checked"}, ...]}.

        Returns:
            The new cached snapshot.
        """
        self._lists = copy.deepcopy(lists)
        await self._broadcast_lists()
        return self._lists

    async def toggle_item(self, list_id: str, item_id: str) -> Dict[str, Any]:
        """
        Flip the `checked` state of a single list item and broadcast the
        updated snapshot.

        Args:
            list_id: The list's id.
            item_id: The item's id within that list.

        Returns:
            The updated list.

        Raises:
            ListsError: If the list or item does not exist.
        """
        for lst in self._lists:
            if lst.get("id") != list_id:
                continue
            for item in lst.get("items", []):
                if item.get("id") == item_id:
                    item["checked"] = not item.get("checked", False)
                    await self._broadcast_lists()
                    return lst
            raise ListsError(f"Item '{item_id}' not found in list '{list_id}'.")
        raise ListsError(f"List '{list_id}' not found.")

    # ─────────────────────────────────────────────────────────────────────────
    # Reminders
    # ─────────────────────────────────────────────────────────────────────────

    def get_reminders(self) -> List[Dict[str, Any]]:
        """Return the cached upcoming-reminders snapshot."""
        return self._reminders

    async def set_reminders(self, reminders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Replace the cached reminders snapshot (pushed by River Song) and
        broadcast `reminders_update` to all connected displays.

        Args:
            reminders: Full reminders snapshot — each item is
                       {"id", "text", "due"}.

        Returns:
            The new cached snapshot.
        """
        self._reminders = copy.deepcopy(reminders)
        await self._broadcast_reminders()
        return self._reminders

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    async def _broadcast_lists(self) -> None:
        await ws_hub.broadcast({"type": "lists_update", "lists": self._lists})

    async def _broadcast_reminders(self) -> None:
        await ws_hub.broadcast({"type": "reminders_update", "reminders": self._reminders})
