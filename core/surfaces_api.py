"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/surfaces_api.py
Purpose:     REST API for surfaces — /api/vortex/v1/surfaces.

             This is how River Song drives the ambient screen. It pushes a
             card descriptor ("bin day tomorrow", "garage still open", "Sam is
             at the front door") and the unit renders it; it withdraws the
             card when the fact stops being true.

             Vortex holds no opinion about what deserves the screen. That
             judgement needs the whole house's context, which lives on the
             server — see core/surfaces.py for why the split sits here.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from connectivity.api_client import APIClient, APIClientError
from core.constants import RIVER_SONG_SURFACES_BASE
from core.surfaces import (MAX_TTL_SECONDS, SURFACE_KINDS, SURFACE_PRIORITIES,
                           SurfaceStore)

logger = logging.getLogger(__name__)

router = APIRouter(prefix=RIVER_SONG_SURFACES_BASE, tags=["Surfaces"])

# ─────────────────────────────────────────────────────────────────────────────
# Store wiring — set once at startup by core.main.create_app()
# ─────────────────────────────────────────────────────────────────────────────

_store: Optional[SurfaceStore] = None


def set_surface_store(store: Optional[SurfaceStore]) -> None:
    """Wire (or clear) the SurfaceStore instance used by these routes."""
    global _store
    _store = store


def _get_store() -> SurfaceStore:
    if _store is None:
        raise HTTPException(status_code=503, detail="Surface subsystem unavailable.")
    return _store


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────

class SurfaceAction(BaseModel):
    """
    A button on a surface.

    `intent` is echoed back to River Song when tapped — the unit never decides
    what an action means, which is what keeps a confirm card from becoming a
    second, weaker permission system on the device.
    """
    label: str = Field(..., min_length=1, max_length=32)
    intent: str = Field(..., min_length=1, max_length=120)
    style: str = Field("default", pattern="^(default|primary|danger)$")


class PushSurfaceRequest(BaseModel):
    """Request body for POST /surfaces — show (or update) one card."""
    id: Optional[str] = Field(None, min_length=1, max_length=120)
    kind: str = Field("note", pattern=f"^({'|'.join(SURFACE_KINDS)})$")
    priority: str = Field("normal", pattern=f"^({'|'.join(SURFACE_PRIORITIES)})$")
    title: str = Field("", max_length=120)
    body: str = Field("", max_length=400)
    value: Optional[str] = Field(None, max_length=32)
    unit: str = Field("", max_length=16)
    items: List[str] = Field(default_factory=list, max_length=8)
    image_url: str = Field("", max_length=500)
    icon: str = Field("", max_length=40)
    actions: List[SurfaceAction] = Field(default_factory=list, max_length=3)
    ttl_seconds: Optional[float] = Field(None, gt=0, le=MAX_TTL_SECONDS)
    #: What River says aloud when this arrives. Required in practice for a
    #: screenless Mini, which has no other way to deliver the card at all.
    speech: Optional[str] = Field(None, max_length=400)


class SurfaceActionRequest(BaseModel):
    """Request body for POST /surfaces/{id}/action — a button was tapped."""
    intent: str = Field(..., min_length=1, max_length=120)


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
async def get_surfaces() -> Dict[str, Any]:
    """
    Return the live surfaces, most important first.

    The kiosk calls this once on load so a browser that starts (or restarts)
    after River Song pushed a card still shows it, rather than waiting for the
    next push that may never come.
    """
    store = _get_store()
    return {"surfaces": store.all()}


@router.post("", status_code=202)
async def push_surface(payload: PushSurfaceRequest) -> Dict[str, Any]:
    """Show a card on this unit, replacing any earlier card with the same id."""
    raw = payload.model_dump(exclude={"speech"})
    raw["actions"] = [a.model_dump() for a in payload.actions]
    surface = await _get_store().push(raw, speech=payload.speech)
    return {"surface": surface}


@router.post("/{surface_id}/action", status_code=202)
async def surface_action(surface_id: str, payload: SurfaceActionRequest) -> Dict[str, Any]:
    """
    Report that someone tapped a button on a card.

    The intent is relayed to River Song verbatim and never interpreted here.
    A confirm card is a prompt, not an authorisation: River Song re-checks
    whether the action is allowed, which is what keeps the wall panel from
    becoming a way around the server's own rules.

    The card is withdrawn only once the relay succeeds — a tap that never
    reached River Song must not look like one that did.
    """
    store = _get_store()

    try:
        result = await APIClient().send_surface_action(surface_id, payload.intent)
    except APIClientError as exc:
        logger.warning("Surface action '%s' could not be delivered: %s",
                       surface_id, exc)
        raise HTTPException(
            status_code=502,
            detail="River Song did not accept the action.",
        ) from exc

    await store.withdraw(surface_id)
    return {"accepted": True, "result": result}


@router.delete("/{surface_id}")
async def withdraw_surface(surface_id: str) -> Dict[str, Any]:
    """Take a card down before it expires — the fact stopped being true."""
    removed = await _get_store().withdraw(surface_id)
    if not removed:
        raise HTTPException(status_code=404, detail="No such surface.")
    return {"removed": surface_id}


@router.delete("")
async def clear_surfaces() -> Dict[str, Any]:
    """Clear every card. Used when a unit is unpaired or re-provisioned."""
    await _get_store().clear()
    return {"cleared": True}
