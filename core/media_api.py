"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/media_api.py
Purpose:     REST API for media playback — /api/vortex/v1/media.

             River Song resolves a spoken request ("play something by
             Fleetwood Mac") into a stream URL plus metadata and POSTs it
             here. The touchscreen uses the same endpoints for its transport
             controls, so voice and touch drive one player.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from audio.media_player import MediaPlayer, MediaPlayerError
from core.constants import RIVER_SONG_MEDIA_BASE

logger = logging.getLogger(__name__)

router = APIRouter(prefix=RIVER_SONG_MEDIA_BASE, tags=["Media"])

# ─────────────────────────────────────────────────────────────────────────────
# Player wiring — set once at startup by core.main.create_app()
# ─────────────────────────────────────────────────────────────────────────────

_player: Optional[MediaPlayer] = None


def set_media_player(player: Optional[MediaPlayer]) -> None:
    """Wire (or clear) the MediaPlayer instance used by these routes."""
    global _player
    _player = player


def _get_player() -> MediaPlayer:
    if _player is None:
        raise HTTPException(status_code=503, detail="Media playback unavailable.")
    return _player


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────

class TrackModel(BaseModel):
    """One playable item. `url` must already be a direct stream URL."""
    url: str = Field(..., min_length=1)
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    artwork_url: Optional[str] = None
    duration_seconds: Optional[int] = None


class PlayBody(BaseModel):
    """Start playback, optionally with an upcoming queue."""
    url: str = Field(..., min_length=1)
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    artwork_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    queue: Optional[List[TrackModel]] = None


class VolumeBody(BaseModel):
    """Set playback volume."""
    level: int = Field(..., ge=0, le=100)


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
async def get_media_state() -> Dict[str, Any]:
    """Return the current transport state — what the now-playing screen reads."""
    return _get_player().get_state()


@router.post("/play")
async def play(body: PlayBody) -> Dict[str, Any]:
    """
    Start playing a stream.

    River Song supplies an already-resolved URL; Vortex does not know which
    service it came from.
    """
    player = _get_player()
    metadata = body.model_dump(exclude={"url", "queue"}, exclude_none=True)
    queue = [t.model_dump(exclude_none=True) for t in (body.queue or [])]

    try:
        await player.play(body.url, metadata, queue=queue or None)
    except MediaPlayerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return player.get_state()


@router.post("/pause")
async def pause() -> Dict[str, Any]:
    """Pause playback, keeping position."""
    player = _get_player()
    await player.pause()
    return player.get_state()


@router.post("/resume")
async def resume() -> Dict[str, Any]:
    """Resume from pause."""
    player = _get_player()
    await player.resume()
    return player.get_state()


@router.post("/toggle")
async def toggle() -> Dict[str, Any]:
    """Pause if playing, resume if paused — the play/pause button."""
    player = _get_player()
    await player.toggle()
    return player.get_state()


@router.post("/next")
async def next_track() -> Dict[str, Any]:
    """
    Skip to the next queued track.

    Raises:
        HTTPException: 409 at the end of the queue, so the caller can say
        "that's the last track" rather than silently doing nothing.
    """
    player = _get_player()
    if not await player.next_track():
        raise HTTPException(status_code=409, detail="No next track in the queue.")
    return player.get_state()


@router.post("/previous")
async def previous_track() -> Dict[str, Any]:
    """Go back one track. 409 at the start of the queue."""
    player = _get_player()
    if not await player.previous_track():
        raise HTTPException(status_code=409, detail="No previous track in the queue.")
    return player.get_state()


@router.delete("")
async def stop_playback() -> Dict[str, Any]:
    """Stop and clear what is playing."""
    player = _get_player()
    await player.stop_playback()
    return player.get_state()


@router.post("/volume")
async def set_volume(body: VolumeBody) -> Dict[str, Any]:
    """Set playback volume, 0–100."""
    player = _get_player()
    await player.set_volume(body.level)
    return player.get_state()
