"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/intercom_api.py
Purpose:     REST API for room-to-room "Drop In" intercom calls
             (/api/vortex/v1/intercom). River Song's voice intent handlers
             ("call the kitchen", "answer", "hang up") drive call control;
             Vortex owns the peer-to-peer UDP call/audio session (see
             intercom/intercom_manager.py) and broadcasts state changes over
             /api/ws as `intercom_update` events.
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

from core.constants import RIVER_SONG_INTERCOM_BASE
from intercom.intercom_manager import IntercomError, IntercomManager
from intercom.unit_discovery import UnitDiscovery

logger = logging.getLogger(__name__)

router = APIRouter(prefix=RIVER_SONG_INTERCOM_BASE, tags=["Intercom"])

# ─────────────────────────────────────────────────────────────────────────────
# Manager wiring — set once at startup by core.main.create_app()
# ─────────────────────────────────────────────────────────────────────────────

_intercom_manager: Optional[IntercomManager] = None


def set_intercom_manager(manager: Optional[IntercomManager]) -> None:
    """Wire (or clear) the IntercomManager instance used by these routes."""
    global _intercom_manager
    _intercom_manager = manager


def _get_manager() -> IntercomManager:
    if _intercom_manager is None:
        raise HTTPException(status_code=503, detail="Intercom subsystem unavailable.")
    return _intercom_manager


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────

class CallRequest(BaseModel):
    """Request body for POST /intercom/call."""
    peer_unit_id: str = Field(..., min_length=1)


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
async def get_intercom_state() -> Dict[str, Any]:
    """Return the current intercom call state (idle, calling, ringing, or active)."""
    return _get_manager().get_state()


@router.get("/peers")
async def list_peers() -> Dict[str, List[Dict[str, Any]]]:
    """List other River Vortex units discovered on the local network."""
    return {"peers": UnitDiscovery().get_peers()}


@router.post("/call", status_code=202)
async def place_call(payload: CallRequest) -> Dict[str, Any]:
    """Place a "Drop In" call to another Vortex unit."""
    try:
        return await _get_manager().call(payload.peer_unit_id)
    except IntercomError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/answer")
async def answer_call() -> Dict[str, Any]:
    """Answer an incoming "Drop In" call."""
    try:
        return await _get_manager().answer()
    except IntercomError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/decline")
async def decline_call() -> Dict[str, Any]:
    """Decline an incoming "Drop In" call."""
    try:
        return await _get_manager().decline()
    except IntercomError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("")
async def hang_up() -> Dict[str, Any]:
    """End the current call (hang up), or no-op if already idle."""
    return await _get_manager().end_call()
