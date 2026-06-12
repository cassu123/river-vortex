"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/lists_api.py
Purpose:     REST API for shopping/to-do lists and upcoming reminders —
             /api/vortex/v1/lists and /api/vortex/v1/reminders. River Song
             owns persistence and pushes the latest snapshot; Vortex caches
             it (core/lists.py) for instant on-screen display and relays
             touch actions (checking off an item) back as broadcasts so all
             connected displays stay in sync.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-12
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.constants import RIVER_SONG_LISTS_BASE, RIVER_SONG_REMINDERS_BASE
from core.lists import ListsError, ListsStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix=RIVER_SONG_LISTS_BASE, tags=["Lists"])
reminders_router = APIRouter(prefix=RIVER_SONG_REMINDERS_BASE, tags=["Reminders"])

# ─────────────────────────────────────────────────────────────────────────────
# Store wiring — set once at startup by core.main.create_app()
# ─────────────────────────────────────────────────────────────────────────────

_store: Optional[ListsStore] = None


def set_lists_store(store: Optional[ListsStore]) -> None:
    """Wire (or clear) the ListsStore instance used by these routes."""
    global _store
    _store = store


def _get_store() -> ListsStore:
    if _store is None:
        raise HTTPException(status_code=503, detail="Lists subsystem unavailable.")
    return _store


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────

class ListItemModel(BaseModel):
    """A single item within a shopping/to-do list."""
    id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    checked: bool = False


class ListModel(BaseModel):
    """A single shopping/to-do list and its items."""
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    items: List[ListItemModel] = Field(default_factory=list)


class SetListsRequest(BaseModel):
    """Request body for POST /lists — replaces the cached snapshot."""
    lists: List[ListModel] = Field(default_factory=list)


class ReminderModel(BaseModel):
    """A single upcoming reminder."""
    id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    due: Optional[str] = None


class SetRemindersRequest(BaseModel):
    """Request body for POST /reminders — replaces the cached snapshot."""
    reminders: List[ReminderModel] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Lists routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
async def get_lists() -> Dict[str, Any]:
    """Return the cached shopping/to-do list snapshot."""
    return {"lists": _get_store().get_lists()}


@router.post("")
async def set_lists(payload: SetListsRequest) -> Dict[str, Any]:
    """Replace the cached list snapshot (called by River Song)."""
    lists = [lst.model_dump() for lst in payload.lists]
    return {"lists": await _get_store().set_lists(lists)}


@router.post("/{list_id}/items/{item_id}/toggle")
async def toggle_list_item(list_id: str, item_id: str) -> Dict[str, Any]:
    """Toggle a list item's checked state."""
    try:
        return await _get_store().toggle_item(list_id, item_id)
    except ListsError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ─────────────────────────────────────────────────────────────────────────────
# Reminders routes
# ─────────────────────────────────────────────────────────────────────────────

@reminders_router.get("")
async def get_reminders() -> Dict[str, Any]:
    """Return the cached upcoming-reminders snapshot."""
    return {"reminders": _get_store().get_reminders()}


@reminders_router.post("")
async def set_reminders(payload: SetRemindersRequest) -> Dict[str, Any]:
    """Replace the cached reminders snapshot (called by River Song)."""
    reminders = [r.model_dump() for r in payload.reminders]
    return {"reminders": await _get_store().set_reminders(reminders)}
