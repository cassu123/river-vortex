"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/timers_api.py
Purpose:     REST API for kitchen timers and alarms
             (/api/vortex/v1/timers). River Song's voice intent handlers
             call this API in response to commands like "set a timer for
             10 minutes" or "cancel the pasta timer" — Vortex owns the
             countdown state, the on-screen display, and the completion
             chime (see core/timers.py).
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-11
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.constants import MAX_TIMER_DURATION_SECONDS, RIVER_SONG_TIMERS_BASE
from core.timers import TimerManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix=RIVER_SONG_TIMERS_BASE, tags=["Timers"])

# ─────────────────────────────────────────────────────────────────────────────
# Manager wiring — set once at startup by core.main.create_app()
# ─────────────────────────────────────────────────────────────────────────────

_timer_manager: Optional[TimerManager] = None


def set_timer_manager(manager: Optional[TimerManager]) -> None:
    """Wire (or clear) the TimerManager instance used by these routes."""
    global _timer_manager
    _timer_manager = manager


def _get_manager() -> TimerManager:
    if _timer_manager is None:
        raise HTTPException(status_code=503, detail="Timer subsystem unavailable.")
    return _timer_manager


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────

class CreateTimerRequest(BaseModel):
    """Request body for POST /timers."""
    duration_seconds: int = Field(..., gt=0, le=MAX_TIMER_DURATION_SECONDS)
    label: str = "Timer"


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
async def list_timers() -> Dict[str, List[Dict[str, Any]]]:
    """Return all active timers/alarms on this unit."""
    return {"timers": _get_manager().list_timers()}


@router.post("", status_code=201)
async def create_timer(payload: CreateTimerRequest) -> Dict[str, Any]:
    """Start a new countdown timer."""
    return await _get_manager().create_timer(payload.duration_seconds, payload.label)


@router.delete("/{timer_id}")
async def cancel_timer(timer_id: str) -> Dict[str, str]:
    """Cancel an active timer by ID."""
    if not await _get_manager().cancel_timer(timer_id):
        raise HTTPException(status_code=404, detail="Timer not found.")
    return {"status": "cancelled"}
