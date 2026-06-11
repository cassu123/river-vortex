"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/setup_api.py
Purpose:     First-run pairing API. Exposes unauthenticated endpoints on the
             local network that the River Song app/browser uses to discover
             this unit, confirm the on-screen pairing PIN, and push River
             Song connection details (and optional unit/HA settings). Once
             paired, the unit persists its configuration and restarts into
             normal operation — analogous to setting up a Google Home device.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-11
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.config import config
from core.constants import RIVER_SONG_SETUP_BASE, SYSTEM_NAME, VERSION
from core.pairing import pairing_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix=RIVER_SONG_SETUP_BASE, tags=["Setup"])

# ─────────────────────────────────────────────────────────────────────────────
# Restart hook — wired up by core.main so this module doesn't need to know
# how the process is supervised.
# ─────────────────────────────────────────────────────────────────────────────

_restart_callback: Optional[Callable[[], None]] = None


def set_restart_callback(callback: Callable[[], None]) -> None:
    """
    Register the function to call after a successful pair/unpair.

    Args:
        callback: A zero-argument callable that restarts River Vortex so
                  the new configuration is picked up by every subsystem.
    """
    global _restart_callback
    _restart_callback = callback


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────

class PairRequest(BaseModel):
    """Payload sent by the River Song app to complete pairing."""

    pin: str = Field(..., description="Pairing PIN currently shown on the unit's display.")
    river_song_api_url: str = Field(..., description="Base URL of the River Song server.")
    river_song_api_key: str = Field(..., description="API key issued by River Song for this unit.")
    unit_name: Optional[str] = Field(None, description="Friendly name, e.g. 'Kitchen Vortex'.")
    location: Optional[str] = Field(None, description="Room/location label, e.g. 'Kitchen'.")
    wake_word: Optional[str] = Field(None, description="Wake word to use for this unit.")
    ha_url: Optional[str] = Field(None, description="Home Assistant base URL.")
    ha_token: Optional[str] = Field(None, description="Home Assistant long-lived access token.")


class UnpairRequest(BaseModel):
    """Payload required to unpair (factory reset pairing) a unit."""

    river_song_api_key: str = Field(..., description="Must match this unit's current API key.")


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/info")
async def get_setup_info() -> dict:
    """
    Return this unit's identity and pairing status.

    Called by the River Song app during device discovery (and periodically
    by this unit's own frontend) to determine whether setup is needed.
    If the unit is not yet configured, a pairing PIN is generated (if one
    doesn't already exist) and included in the response for display.

    Returns:
        A dict describing the unit, its hardware, and pairing state.
    """
    configured = bool(config.get("configured", False))

    info = {
        "system": SYSTEM_NAME,
        "version": VERSION,
        "unit_id": config.get("unit_id"),
        "unit_name": config.get("unit_name"),
        "location": config.get("location"),
        "configured": configured,
        "hardware": {
            "screen": config.get("hw_screen"),
            "mic_array": config.get("hw_mic_array"),
            "speakers": config.get("hw_speakers"),
        },
    }

    if not configured:
        info["pairing_pin"] = pairing_session.pin or pairing_session.generate()

    return info


@router.post("/pair")
async def pair(payload: PairRequest) -> dict:
    """
    Complete pairing with River Song.

    Validates the pairing PIN, persists the supplied River Song (and
    optional unit/Home Assistant) configuration to the unit profile, then
    triggers a restart so all subsystems start fresh with the new config.

    Args:
        payload: Pairing details submitted by the River Song app.

    Returns:
        A dict confirming pairing succeeded and a restart is underway.

    Raises:
        HTTPException: 409 if already paired, 403 if the PIN is invalid.
    """
    if config.get("configured", False):
        raise HTTPException(
            status_code=409,
            detail="This unit is already paired with River Song. Unpair it first.",
        )

    if not pairing_session.verify(payload.pin):
        raise HTTPException(status_code=403, detail="Invalid or expired pairing PIN.")

    updates = {
        "configured": True,
        "river_song_api_url": payload.river_song_api_url,
        "river_song_api_key": payload.river_song_api_key,
    }
    for field, key in (
        ("unit_name", "unit_name"),
        ("location", "location"),
        ("wake_word", "wake_word"),
        ("ha_url", "ha_url"),
        ("ha_token", "ha_token"),
    ):
        value = getattr(payload, field)
        if value:
            updates[key] = value

    config.save_profile(updates)
    pairing_session.clear()
    logger.info("Pairing complete (River Song: %s). Restarting...", payload.river_song_api_url)

    if _restart_callback:
        _restart_callback()

    return {"status": "paired", "restarting": True}


@router.post("/unpair")
async def unpair(payload: UnpairRequest) -> dict:
    """
    Unpair this unit from River Song and return it to setup mode.

    Requires the caller to know the unit's current River Song API key,
    which only River Song (or someone with access to it) would have.

    Args:
        payload: Must contain the unit's current River Song API key.

    Returns:
        A dict confirming the unit is unpaired and a restart is underway.

    Raises:
        HTTPException: 409 if not currently paired, 403 if the key is wrong.
    """
    if not config.get("configured", False):
        raise HTTPException(status_code=409, detail="This unit is not currently paired.")

    current_key = config.get("river_song_api_key", "")
    if not current_key or payload.river_song_api_key != current_key:
        raise HTTPException(status_code=403, detail="Invalid River Song API key.")

    config.save_profile({"configured": False, "river_song_api_key": ""})
    pairing_session.generate()
    logger.info("Unit unpaired from River Song. Restarting into setup mode...")

    if _restart_callback:
        _restart_callback()

    return {"status": "unpaired", "restarting": True}
