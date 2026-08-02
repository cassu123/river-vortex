"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/settings_api.py
Purpose:     Device settings — /api/vortex/v1/settings.

             These are settings for THIS BOX, not for a person. Volume,
             brightness, whether the microphone is muted, how eagerly this
             unit wakes. A Google Home works the same way: your account
             preferences live in the app, but the speaker's own knobs belong
             to the speaker.

             There is deliberately no user concept here. Nothing on this
             screen changes depending on who is standing in front of it, and
             nothing here needs an account — which is exactly why it keeps
             working when River Song is unreachable. That is the point of
             having it on the device at all: the moment you most need to turn
             the volume down or mute the mic is the moment the network is
             down and the app cannot reach you.

             Per-device configuration managed centrally — the room a unit is
             in, the household wake word, what it is allowed to show — lives
             in River Song, under that device's page. This is the other half.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.config import config
from core.constants import RIVER_SONG_SETTINGS_BASE, VERSION

logger = logging.getLogger(__name__)

router = APIRouter(prefix=RIVER_SONG_SETTINGS_BASE, tags=["Settings"])

# ─────────────────────────────────────────────────────────────────────────────
# Subsystem wiring — set once at startup by core.main
# ─────────────────────────────────────────────────────────────────────────────

_audio_manager: Optional[Any] = None
_screen_manager: Optional[Any] = None
_privacy_manager: Optional[Any] = None
_wake_word: Optional[Any] = None


def set_subsystems(audio_manager: Any = None, screen_manager: Any = None,
                   privacy_manager: Any = None, wake_word: Any = None) -> None:
    """
    Wire the subsystems these settings drive.

    Anything left None makes its setting read-only rather than an error: a
    screenless Mini has no brightness, and a unit with no camera has no camera
    mute. The screen asks what exists and draws only that.
    """
    global _audio_manager, _screen_manager, _privacy_manager, _wake_word
    if audio_manager is not None:
        _audio_manager = audio_manager
    if screen_manager is not None:
        _screen_manager = screen_manager
    if privacy_manager is not None:
        _privacy_manager = privacy_manager
    if wake_word is not None:
        _wake_word = wake_word


# ─────────────────────────────────────────────────────────────────────────────
# Request model
# ─────────────────────────────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    """
    A change to one or more device settings.

    Every field is optional: the screen sends only what the user actually
    moved, so two people adjusting different things cannot overwrite each
    other with stale values for the rest.
    """
    volume: Optional[int] = Field(None, ge=0, le=100)
    brightness: Optional[int] = Field(None, ge=0, le=100)
    mic_muted: Optional[bool] = None
    camera_muted: Optional[bool] = None
    #: Higher is stricter — fewer false wakes, more missed ones.
    wake_word_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
async def get_settings() -> Dict[str, Any]:
    """
    Everything the settings screen needs to draw itself.

    `capabilities` says which controls this unit can actually offer, so the
    screen never shows a brightness slider on a unit with no backlight or a
    camera toggle on a unit with no camera.
    """
    privacy = _privacy_manager.get_state() if _privacy_manager else {}

    camera_fitted = False
    try:
        from display.camera import camera
        camera_fitted = camera.fitted
    except Exception:  # pylint: disable=broad-except
        pass

    uplink = False
    try:
        from connectivity.vortex_link import vortex_link
        uplink = vortex_link.connected
    except Exception:  # pylint: disable=broad-except
        pass

    return {
        # Adjustable here.
        "volume": int(config.get("volume", 70)),
        "brightness": (_screen_manager.get_brightness()
                       if _screen_manager else int(config.get("screen_brightness", 80))),
        "mic_muted": bool(privacy.get("mic_muted", False)),
        "camera_muted": bool(privacy.get("cam_muted", False)),
        "camera_active": bool(privacy.get("cam_active", False)),
        "wake_word_threshold": (_wake_word.threshold if _wake_word
                                else float(config.get("wake_word_threshold", 0.5))),

        # Read-only. Shown so someone standing at the panel can answer "which
        # unit is this and is it talking to the server", which is most of what
        # anyone actually opens settings for.
        "unit_id": config.get("unit_id", ""),
        "unit_name": config.get("unit_name", ""),
        "location": config.get("location", ""),
        "version": VERSION,
        "wake_word": config.get("wake_word", ""),
        "uplink_connected": uplink,

        "capabilities": {
            "volume": _audio_manager is not None,
            "brightness": _screen_manager is not None,
            "microphone": _privacy_manager is not None,
            "camera": camera_fitted and _privacy_manager is not None,
            "wake_word": _wake_word is not None,
        },
    }


@router.post("")
async def update_settings(payload: SettingsUpdate) -> Dict[str, Any]:
    """
    Apply a settings change.

    Applied to the live subsystem first so the effect is immediate, then
    persisted to the unit profile so it survives a reboot. A control the unit
    does not have is reported back rather than silently ignored — a slider
    that appears to do nothing is worse than one that says why.

    Note River Song stays authoritative: if it later pushes a different value
    over the replica, that wins. This is the local override for right now, on
    this box, in front of this person.
    """
    applied: Dict[str, Any] = {}
    refused: Dict[str, str] = {}
    persist: Dict[str, Any] = {}

    if payload.volume is not None:
        if _audio_manager is None:
            refused["volume"] = "this unit has no audio output"
        else:
            _audio_manager.set_volume(payload.volume)
            applied["volume"] = payload.volume
            persist["volume"] = payload.volume

    if payload.brightness is not None:
        if _screen_manager is None:
            refused["brightness"] = "this unit has no screen"
        else:
            _screen_manager.set_brightness(payload.brightness)
            applied["brightness"] = payload.brightness
            persist["screen_brightness"] = payload.brightness

    if payload.mic_muted is not None:
        if _privacy_manager is None:
            refused["mic_muted"] = "privacy controls unavailable"
        else:
            if payload.mic_muted:
                _privacy_manager.mute_microphone()
            else:
                _privacy_manager.unmute_microphone()
            applied["mic_muted"] = payload.mic_muted
            # Deliberately NOT persisted. A mic that silently comes back
            # muted after a power cut is a unit that looks broken; a mic that
            # comes back live is at least honest, and the LED says so.

    if payload.camera_muted is not None:
        if _privacy_manager is None:
            refused["camera_muted"] = "privacy controls unavailable"
        else:
            if payload.camera_muted:
                _privacy_manager.mute_camera()
            else:
                _privacy_manager.unmute_camera()
            applied["camera_muted"] = payload.camera_muted

    if payload.wake_word_threshold is not None:
        if _wake_word is None:
            refused["wake_word_threshold"] = "wake word detection is not running"
        elif _wake_word.set_threshold(payload.wake_word_threshold):
            applied["wake_word_threshold"] = payload.wake_word_threshold
            persist["wake_word_threshold"] = payload.wake_word_threshold

    if persist:
        try:
            config.save_profile(persist)
        except Exception as exc:  # pylint: disable=broad-except
            # The change is already live; failing to write it down is worth
            # saying but not worth undoing what the user just did.
            logger.error("Settings applied but not persisted: %s", exc)

    if not applied and refused:
        raise HTTPException(status_code=409, detail=refused)

    logger.info("Device settings changed: %s", applied)
    return {"applied": applied, "refused": refused}
