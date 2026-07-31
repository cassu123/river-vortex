"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/diagnostics_api.py
Purpose:     REST access to the boot self-test — /api/vortex/v1/diagnostics.

             Results also stream over the WebSocket as they complete, but the
             kiosk browser normally finishes starting AFTER the backend, so it
             would miss the live stream. This endpoint lets it fetch whatever
             has already run and catch up mid-boot.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from core.constants import RIVER_SONG_DIAGNOSTICS_BASE
from core.diagnostics import Diagnostics

logger = logging.getLogger(__name__)

router = APIRouter(prefix=RIVER_SONG_DIAGNOSTICS_BASE, tags=["Diagnostics"])

_diagnostics: Optional[Diagnostics] = None


def set_diagnostics(diagnostics: Optional[Diagnostics]) -> None:
    """Wire (or clear) the Diagnostics instance used by these routes."""
    global _diagnostics
    _diagnostics = diagnostics


@router.get("")
async def get_diagnostics() -> Dict[str, Any]:
    """Return the current (or last completed) self-test report."""
    if _diagnostics is None:
        raise HTTPException(status_code=503, detail="Diagnostics unavailable.")
    return _diagnostics.get_report()


@router.post("/run")
async def rerun_diagnostics() -> Dict[str, Any]:
    """
    Re-run the self-test on demand.

    Useful after plugging in a microphone or fixing a power supply, without
    rebooting the unit.
    """
    if _diagnostics is None:
        raise HTTPException(status_code=503, detail="Diagnostics unavailable.")
    await _diagnostics.run()
    return _diagnostics.get_report()
