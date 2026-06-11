"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/routines_api.py
Purpose:     REST API for guided routine sessions — cooking mode, workout
             mode, bedtime checklists, and similar step-by-step walkthroughs
             (/api/vortex/v1/routine). River Song supplies the routine title
             and steps and recognizes follow-up voice commands ("next step",
             "go back", "repeat that", "done"); Vortex owns the step state,
             on-screen display, and ducks/restores background media for the
             duration (see core/routines.py).
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

from core.constants import RIVER_SONG_ROUTINE_BASE
from core.routines import RoutineError, RoutineSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix=RIVER_SONG_ROUTINE_BASE, tags=["Routines"])

# ─────────────────────────────────────────────────────────────────────────────
# Session wiring — set once at startup by core.main.create_app()
# ─────────────────────────────────────────────────────────────────────────────

_routine_session: Optional[RoutineSession] = None


def set_routine_session(session: Optional[RoutineSession]) -> None:
    """Wire (or clear) the RoutineSession instance used by these routes."""
    global _routine_session
    _routine_session = session


def _get_session() -> RoutineSession:
    if _routine_session is None:
        raise HTTPException(status_code=503, detail="Routine subsystem unavailable.")
    return _routine_session


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────

class RoutineStepRequest(BaseModel):
    """A single guided routine step."""
    instruction: str = Field(..., min_length=1)
    duration_seconds: Optional[int] = Field(None, gt=0)


class StartRoutineRequest(BaseModel):
    """Request body for POST /routine."""
    title: str = Field(..., min_length=1)
    steps: List[RoutineStepRequest] = Field(..., min_length=1)


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
async def get_routine() -> Dict[str, Any]:
    """Return the current routine state (active or not)."""
    return _get_session().get_state()


@router.post("", status_code=201)
async def start_routine(payload: StartRoutineRequest) -> Dict[str, Any]:
    """Begin a new guided routine, replacing any in-progress routine."""
    steps = [step.model_dump(exclude_none=True) for step in payload.steps]
    try:
        return await _get_session().start(payload.title, steps)
    except RoutineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/next")
async def advance_routine() -> Dict[str, Any]:
    """Advance to the next step, or stop the routine if already on the last step."""
    try:
        return await _get_session().next_step()
    except RoutineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/previous")
async def reverse_routine() -> Dict[str, Any]:
    """Go back to the previous step (no-op on the first step)."""
    try:
        return await _get_session().previous_step()
    except RoutineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("")
async def stop_routine() -> Dict[str, Any]:
    """End the active routine."""
    try:
        return await _get_session().stop()
    except RoutineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
