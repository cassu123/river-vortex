"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/announce_api.py
Purpose:     REST API for multi-room announcements / "Drop In" broadcasts
             (/api/vortex/v1/announce). River Song receives a voice intent
             (e.g., "announce to all rooms: dinner's ready") on one unit,
             then calls this endpoint on every paired Vortex unit — including
             this one — to play and display the message. Vortex owns the
             on-screen banner, speaker playback, and media ducking for the
             duration (see core/announce.py).
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-12
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.announce import AnnouncementSession
from core.constants import (
    ANNOUNCEMENT_MAX_DURATION_SECONDS,
    ANNOUNCEMENT_MAX_MESSAGE_LENGTH,
    RIVER_SONG_ANNOUNCE_BASE,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix=RIVER_SONG_ANNOUNCE_BASE, tags=["Announcements"])

# ─────────────────────────────────────────────────────────────────────────────
# Session wiring — set once at startup by core.main.create_app()
# ─────────────────────────────────────────────────────────────────────────────

_session: Optional[AnnouncementSession] = None


def set_announcement_session(session: Optional[AnnouncementSession]) -> None:
    """Wire (or clear) the AnnouncementSession instance used by these routes."""
    global _session
    _session = session


def _get_session() -> AnnouncementSession:
    if _session is None:
        raise HTTPException(status_code=503, detail="Announcement subsystem unavailable.")
    return _session


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────

class AnnounceRequest(BaseModel):
    """Request body for POST /announce — a "Drop In" / broadcast message."""
    message: str = Field(..., min_length=1, max_length=ANNOUNCEMENT_MAX_MESSAGE_LENGTH)
    source: Optional[str] = Field(None, max_length=100)
    priority: str = Field("normal", pattern="^(normal|urgent)$")
    audio_url: Optional[str] = None
    duration_seconds: Optional[float] = Field(None, gt=0, le=ANNOUNCEMENT_MAX_DURATION_SECONDS)


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@router.post("", status_code=202)
async def post_announcement(payload: AnnounceRequest) -> Dict[str, Any]:
    """Play an announcement on this unit (e.g., a phone → house or room → room "Drop In")."""
    return await _get_session().announce(
        message=payload.message,
        source=payload.source,
        priority=payload.priority,
        audio_url=payload.audio_url,
        duration_seconds=payload.duration_seconds,
    )
