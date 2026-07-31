"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/photos_api.py
Purpose:     REST API for the ambient photo backdrop —
             /api/vortex/v1/photos. The kiosk asks for the playlist once,
             then fetches each image by name and crossfades between them.

             Images are served by name resolved against the scanned library,
             never by a path joined onto user input, so this endpoint cannot
             be walked out of the photo directory.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
import mimetypes
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core.config import config
from core.constants import AMBIENT_PHOTO_INTERVAL_SECONDS, RIVER_SONG_PHOTOS_BASE
from display.photo_library import PhotoLibrary

logger = logging.getLogger(__name__)

router = APIRouter(prefix=RIVER_SONG_PHOTOS_BASE, tags=["Photos"])

# ─────────────────────────────────────────────────────────────────────────────
# Library wiring — set once at startup by core.main.create_app()
# ─────────────────────────────────────────────────────────────────────────────

_library: Optional[PhotoLibrary] = None


def set_photo_library(library: Optional[PhotoLibrary]) -> None:
    """Wire (or clear) the PhotoLibrary instance used by these routes."""
    global _library
    _library = library


def _get_library() -> PhotoLibrary:
    if _library is None:
        raise HTTPException(status_code=503, detail="Photo library unavailable.")
    return _library


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
async def list_photos() -> dict:
    """
    Return the ambient photo playlist and how long to hold each frame.

    An empty list is a normal, expected response — a unit with no photos
    configured simply falls back to the plain gradient backdrop.
    """
    library = _get_library()
    names = library.names()
    return {
        "photos": [{"name": n, "url": f"{RIVER_SONG_PHOTOS_BASE}/file/{n}"} for n in names],
        "count": len(names),
        "interval_seconds": int(
            config.get("photo_interval_seconds", AMBIENT_PHOTO_INTERVAL_SECONDS)
        ),
    }


@router.get("/file/{name}")
async def get_photo(name: str) -> FileResponse:
    """
    Serve a single photo by filename.

    Args:
        name: A filename from the playlist returned by list_photos().

    Raises:
        HTTPException: 404 if the name is not in the library.

    The name is matched against the scanned set rather than joined onto the
    photo directory, so traversal attempts simply miss.
    """
    library = _get_library()
    path = library.resolve(name)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Photo not found.")

    media_type, _ = mimetypes.guess_type(path.name)
    return FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
        # These files change rarely and the panel refetches them all day.
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.post("/rescan")
async def rescan_photos() -> dict:
    """
    Rescan the photo directory immediately.

    Called after River Song drops new files onto the unit, so they appear
    without waiting for the periodic rescan or a restart.
    """
    library = _get_library()
    count = library.rescan()
    logger.info("Photo library rescanned on request: %d photo(s).", count)
    return {"status": "ok", "count": count}
