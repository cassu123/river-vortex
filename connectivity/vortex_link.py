"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        connectivity/vortex_link.py
Purpose:     The uplink — one persistent WebSocket from this unit to River Song.

             Everything River Song decides arrives here: which card belongs on
             the screen, what music to play, what River is doing right now, the
             envelope that makes the orb pulse while she speaks, and the device
             and camera lists the dashboards render from.

             The unit DIALS OUT. Nothing ever connects inbound to a Pi sitting
             on a home network, which is why this exists at all rather than
             River Song POSTing to the unit's own REST API.

             Nothing here interprets anything. A frame arrives, it is handed to
             whichever local subsystem already owns that concern — the surface
             store, the media player, the presence broadcaster — and those
             subsystems behave exactly as they do when a human drives them
             through the touchscreen. This module is a wire, not a brain.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import base64
import json
import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

from core.config import config
from core.constants import RIVER_SONG_WS_ENDPOINT
from core.ws_hub import ws_hub

logger = logging.getLogger(__name__)

#: River Song drops a socket that has not authenticated within five seconds,
#: so the auth frame goes out before anything else is awaited.
AUTH_TIMEOUT_SECONDS = 5.0

#: Reconnect backoff. A unit whose WiFi has gone should not hammer a router,
#: but a unit that reconnects in ten minutes is a unit that missed the doorbell.
RECONNECT_MIN_SECONDS = 2.0
RECONNECT_MAX_SECONDS = 60.0

#: Keepalive. Home routers drop idle connections, and a socket that is quietly
#: dead looks exactly like a socket with nothing to say.
PING_INTERVAL_SECONDS = 30.0

#: Bytes of raw PCM per audio_chunk frame.
#:
#: River Song rejects a decoded chunk over 128 KiB. This sits under that with
#: headroom — at 16kHz mono s16le it is three seconds per frame, so a long
#: command becomes several frames rather than one oversized one that is
#: dropped outright.
AUDIO_CHUNK_BYTES = 96 * 1024


def _ws_url(base_url: str, unit_id: str) -> str:
    """
    Build the uplink URL from River Song's HTTP base.

    The unit id goes on the query string as well as in the auth frame: it lets
    River Song refuse an unknown unit before completing the handshake, rather
    than accepting a socket it is about to throw away.
    """
    parts = urlsplit(base_url.rstrip("/"))
    scheme = {"http": "ws", "https": "wss"}.get(parts.scheme, parts.scheme)
    if scheme not in ("ws", "wss"):
        raise ValueError(f"Cannot derive a WebSocket URL from {base_url!r}.")
    query = f"unit_id={unit_id}"
    return urlunsplit((scheme, parts.netloc, RIVER_SONG_WS_ENDPOINT, query, ""))


class VortexLink:
    """
    The unit's connection to River Song.

    Usage:
        link = VortexLink(surface_store=surfaces, media_player=player)
        await link.start()
        ...
        await link.stop()

    Runs a reconnect loop for the lifetime of the unit. A unit with no network
    is not broken, it is offline: it keeps its clock, its photos and its local
    voice, and picks the connection back up when WiFi returns.
    """

    def __init__(self, surface_store: Any = None, media_player: Any = None,
                 audio_manager: Any = None, wake_word: Any = None) -> None:
        """
        Args:
            surface_store: core.surfaces.SurfaceStore — receives pushed cards.
            media_player:  audio.media_player.MediaPlayer — receives playback.
            audio_manager: audio.audio_manager.AudioManager — plays TTS audio.
            wake_word:     audio.wake_word.WakeWordDetector — retuned when
                           River Song reports a new household wake word.
        """
        self._surfaces = surface_store
        self._media = media_player
        self._audio = audio_manager
        self._wake_word = wake_word

        self._socket = None
        self._task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._running = False
        self._connected = False
        self._backoff = RECONNECT_MIN_SECONDS
        self._last_reply_at = 0.0

    def attach(self, surface_store: Any = None, media_player: Any = None,
               audio_manager: Any = None, wake_word: Any = None) -> None:
        """
        Wire the subsystems pushed frames are handed to.

        Separate from the constructor because this is a module-level
        singleton, built at import time and populated by the orchestrator once
        the subsystems it feeds actually exist. Anything left None makes the
        matching frame type a no-op rather than an error — a screenless Mini
        has no surface store to hand a card to, and that is not a fault.
        """
        if surface_store is not None:
            self._surfaces = surface_store
        if media_player is not None:
            self._media = media_player
        if audio_manager is not None:
            self._audio = audio_manager
        if wake_word is not None:
            self._wake_word = wake_word

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        """True while the uplink is open and authenticated."""
        return self._connected

    async def start(self) -> None:
        """Begin connecting, and keep reconnecting for as long as we run."""
        if self._running:
            return
        if not config.get("river_song_api_key", ""):
            # An unpaired unit has no token, so there is nothing to
            # authenticate with. It will get one from the pairing flow and the
            # orchestrator starts the link again after the restart.
            logger.info("Vortex uplink not started — unit is unpaired.")
            return
        self._running = True
        self._task = asyncio.create_task(self._run_forever(), name="vortex-uplink")
        logger.info("Vortex uplink starting.")

    async def stop(self) -> None:
        """Close the uplink and stop reconnecting."""
        self._running = False
        for task in (self._ping_task, self._task):
            if task and not task.done():
                task.cancel()
        await self._close_socket()
        logger.info("Vortex uplink stopped.")

    # ─────────────────────────────────────────────────────────────────────────
    # Sending
    # ─────────────────────────────────────────────────────────────────────────

    async def send(self, frame_type: str, payload: Optional[Dict] = None) -> bool:
        """
        Send one frame to River Song.

        Args:
            frame_type: One of the unit→server types — `state`, `ack`,
                `occupancy`, `audio_chunk`, `camera_state`, `ping`.
            payload:    Merged into the frame alongside `type`.

        Returns:
            False if the uplink is down. Callers treat that as "River Song did
            not hear this", never as an error worth stopping for — a unit
            offline is a normal state, not a fault.
        """
        if not self._connected or self._socket is None:
            return False
        try:
            await self._socket.send(json.dumps({"type": frame_type, **(payload or {})}))
            return True
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Uplink send '%s' failed: %s", frame_type, exc)
            return False

    async def report_state(self, state: str) -> None:
        """
        Tell River Song what this unit is doing.

        A report, not a request. River Song decides what to do about it.
        """
        await self.send("state", {"state": state})

    async def send_utterance(self, audio: bytes) -> bool:
        """
        Send a captured command to River Song, in frames.

        The reply does NOT come back from this call. River Song transcribes,
        routes the intent, synthesises, and pushes `presence` and `audio`
        frames back over this same socket — which is why the voice path moved
        here from a REST POST: one socket, one auth path, and the orb can
        track River's answer while she gives it.

        Args:
            audio: Raw PCM, 16kHz mono s16le, captured after the wake word.

        Returns:
            False if the uplink is down, meaning the command was never heard.

        NOTE ON LENGTH: River Song currently discards every chunk marked
        `final=False`, so only the last frame is transcribed and any command
        over ~4 seconds is silently dropped server-side. The chunking below is
        correct regardless and is deliberately written for the fixed server:
        the moment it accumulates non-final chunks, long commands start
        working with no change here.
        """
        if not audio:
            return False
        if not self._connected:
            return False

        total = len(audio)
        sent = 0
        while sent < total:
            piece = audio[sent:sent + AUDIO_CHUNK_BYTES]
            sent += len(piece)
            ok = await self.send("audio_chunk", {
                "data": base64.b64encode(piece).decode("ascii"),
                "final": sent >= total,
            })
            if not ok:
                logger.warning("Utterance cut short — uplink dropped mid-send.")
                return False

        logger.debug("Sent %d bytes of command audio in %d frame(s).",
                     total, (total + AUDIO_CHUNK_BYTES - 1) // AUDIO_CHUNK_BYTES)
        return True

    async def report_camera(self, camera_state: Dict[str, Any]) -> None:
        """
        Declare what this unit's camera is fitted with and consented to.

        This only ever NARROWS what River Song will ask for. It is sent on
        connect so the server never requests a capture the unit would refuse.
        """
        await self.send("camera_state", {"camera": camera_state})

    # ─────────────────────────────────────────────────────────────────────────
    # The connection loop
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_forever(self) -> None:
        """Connect, serve, and reconnect with backoff until stopped."""
        while self._running:
            try:
                await self._connect_once()
                self._backoff = RECONNECT_MIN_SECONDS
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pylint: disable=broad-except
                logger.info("Vortex uplink down (%s); retrying in %.0fs.",
                            exc, self._backoff)
            finally:
                await self._on_disconnected()

            if not self._running:
                break
            await asyncio.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, RECONNECT_MAX_SECONDS)

    async def _connect_once(self) -> None:
        """Open the socket, authenticate, then serve frames until it closes."""
        import websockets

        base = config.get("river_song_api_url", "http://riversong.local")
        unit_id = config.get("unit_id", "vortex-unset")
        token = config.get("river_song_api_key", "")
        url = _ws_url(base, unit_id)

        logger.debug("Vortex uplink connecting to %s", url)
        async with websockets.connect(url, open_timeout=AUTH_TIMEOUT_SECONDS,
                                      ping_interval=None) as socket:
            self._socket = socket

            # The auth frame must be first and must land inside River Song's
            # five second window, so it goes out before anything else awaits.
            await socket.send(json.dumps(
                {"type": "auth", "unit_id": unit_id, "token": token}))

            raw = await asyncio.wait_for(socket.recv(), timeout=AUTH_TIMEOUT_SECONDS)
            frame = json.loads(raw)
            if frame.get("type") != "auth_ok":
                raise RuntimeError(f"uplink refused: {frame.get('type')!r}")

            await self._on_authenticated(frame)

            async for message in socket:
                try:
                    await self._dispatch(json.loads(message))
                except Exception as exc:  # pylint: disable=broad-except
                    # One malformed or unhandled frame must never take the
                    # uplink down with it.
                    logger.warning("Uplink frame failed: %s", exc)

    async def _on_authenticated(self, frame: Dict[str, Any]) -> None:
        """Record the connection and tell River Song what we are."""
        self._connected = True
        logger.info("Vortex uplink connected as %s (room=%s, display=%s).",
                    frame.get("unit_id"), frame.get("room") or "unset",
                    frame.get("has_display"))

        await ws_hub.broadcast({"type": "uplink", "connected": True})

        # Declare the camera immediately, so River Song knows what it may ask
        # for before it has a chance to ask for anything.
        try:
            from display.camera import camera
            await self.report_camera(camera.get_state())
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Camera state not reported: %s", exc)

        self._ping_task = asyncio.create_task(self._ping_loop(), name="uplink-ping")

    async def _on_disconnected(self) -> None:
        """Clear connection state and let the screen know."""
        was_connected = self._connected
        self._connected = False
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
        await self._close_socket()
        if was_connected:
            try:
                await ws_hub.broadcast({"type": "uplink", "connected": False})
            except Exception:  # pylint: disable=broad-except
                pass

    async def _close_socket(self) -> None:
        if self._socket is not None:
            try:
                await self._socket.close()
            except Exception:  # pylint: disable=broad-except
                pass
            self._socket = None

    async def _ping_loop(self) -> None:
        """Keep the socket alive through a router that drops idle connections."""
        try:
            while self._connected:
                await asyncio.sleep(PING_INTERVAL_SECONDS)
                if not await self.send("ping"):
                    return
        except asyncio.CancelledError:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Dispatch — server frame to the local subsystem that already owns it
    # ─────────────────────────────────────────────────────────────────────────

    @property
    def last_reply_at(self) -> float:
        """
        Monotonic timestamp of the last frame that counts as River answering.

        Lets a caller that handed over an utterance tell "she replied" from
        "the server went quiet", without this module needing to know anything
        about the voice flow.
        """
        return self._last_reply_at

    async def _dispatch(self, frame: Dict[str, Any]) -> None:
        """Route one server→unit frame."""
        kind = str(frame.get("type") or "")

        # Anything River initiates counts as an answer. Deliberately not
        # `replica` or the feed updates: those arrive on a timer and would
        # make a silent server look responsive.
        if kind in ("presence", "amplitude", "audio", "surface", "media"):
            self._last_reply_at = time.monotonic()

        if kind == "surface":
            await self._on_surface(frame)
        elif kind == "surface_withdraw":
            # River Song's name for it; the local store and the browser both
            # call this "remove". Translated here so one rename on either side
            # is a one-line change in one file.
            if self._surfaces is not None:
                await self._surfaces.withdraw(str(frame.get("id") or ""))
        elif kind == "media":
            await self._on_media(frame)
        elif kind == "audio":
            await self._on_audio(frame)
        elif kind == "presence":
            await self._on_presence(frame)
        elif kind == "replica":
            await self._on_replica(frame)
        elif kind in ("amplitude", "navigate",
                      "devices_update", "cameras_update", "notifications_update"):
            # Straight through to the browser. These are exactly the message
            # types App.jsx already handles, so no translation is wanted —
            # translating would be two vocabularies free to drift apart.
            await ws_hub.broadcast(frame)
        elif kind == "pong":
            pass
        else:
            logger.debug("Uplink ignored frame type '%s'.", kind)

    async def _on_presence(self, frame: Dict[str, Any]) -> None:
        """
        Relay River's state to the screen — and say it aloud when there is no
        screen to relay it to.

        River Song reports some failures purely as presence: an utterance over
        its length limit comes back as state `error` with a caption, and
        nothing else. On a Hub that lands on the orb and reads fine. On a
        screenless Mini it lands nowhere at all — no browser, no orb — so the
        user gets total silence and no idea why.

        Only error captions are spoken. Narrating every state change would
        make a Mini unbearable, but a failure that goes unmentioned is the
        thing that makes a unit feel broken.
        """
        await ws_hub.broadcast(frame)

        data = frame.get("data") or {}
        if str(data.get("state") or "") != "error":
            return
        caption = str(data.get("caption") or "").strip()
        if not caption:
            return

        try:
            from core.presenter import presenter
            if presenter.has_screen:
                return
            from core.voice import voice
            await voice.speak(caption, interrupt=False, prefer_local=True)
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Could not speak presence caption: %s", exc)

    async def _on_replica(self, frame: Dict[str, Any]) -> None:
        """
        Take a state snapshot from River Song.

        Relayed to the screen unchanged, and two fields are acted on here.

        The wake word phrase is a household choice — "hey river", "sup river",
        whatever the user picked — so changing it in their profile reaches
        every unit without anyone reflashing a Pi.

        The detection threshold is PER UNIT, and deliberately so: a kitchen
        panel next to a dishwasher needs a different setting from a bedroom
        one, and the whole point of tuning it is that some rooms are harder
        than others. It arrives in the unit's own settings block.
        """
        await ws_hub.broadcast(frame)

        if self._wake_word is None:
            return

        phrase = frame.get("wake_word")
        if phrase:
            try:
                await self._wake_word.set_wake_word(str(phrase))
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Could not apply wake word '%s': %s", phrase, exc)

        settings = frame.get("settings") or {}
        threshold = settings.get("wake_word_threshold",
                                 frame.get("wake_word_threshold"))
        if threshold is not None:
            self._wake_word.set_threshold(threshold)

    async def _on_surface(self, frame: Dict[str, Any]) -> None:
        """
        Hand a pushed card to the local surface store.

        Going through the store rather than straight to the browser is what
        makes a pushed card behave identically to a locally-posted one: it gets
        the same TTL handling, the same priority ordering, the same screen
        wake, and the same spoken delivery on a screenless Mini.
        """
        if self._surfaces is None:
            return
        card = {k: v for k, v in frame.items() if k != "type"}
        await self._surfaces.push(card, speech=card.get("speech"))

    async def _on_media(self, frame: Dict[str, Any]) -> None:
        """Play what River Song resolved, on this unit's own speaker."""
        if self._media is None:
            return
        action = str(frame.get("action") or "play")
        track = dict(frame.get("track") or {})

        if action == "play":
            url = track.pop("url", "")
            if not url:
                logger.warning("Uplink media play carried no URL; ignoring.")
                return
            # play() takes the URL separately from the display metadata, and
            # the queue entries keep their own urls.
            await self._media.play(url, metadata=track,
                                   queue=frame.get("queue") or None)
        elif action == "pause":
            await self._media.pause()
        elif action == "resume":
            await self._media.resume()
        elif action == "stop":
            # stop_playback(), NOT stop(): the latter shuts mpv down entirely
            # and the unit would go silent until it was restarted.
            await self._media.stop_playback()
        elif action == "next":
            await self._media.next_track()
        elif action == "previous":
            await self._media.previous_track()
        elif action == "volume":
            level = frame.get("value")
            if isinstance(level, (int, float)):
                await self._media.set_volume(int(level))
        else:
            logger.debug("Uplink ignored media action '%s'.", action)

    async def _on_audio(self, frame: Dict[str, Any]) -> None:
        """Play a TTS response River Song pushed rather than returned."""
        if self._audio is None:
            return
        payload = frame.get("audio") or frame.get("data") or ""
        if not payload:
            return
        try:
            wav = base64.b64decode(payload)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Uplink audio frame was not valid base64: %s", exc)
            return
        self._audio.speaker.play(wav, interrupt=True)


# Module-level singleton, wired with its subsystems at startup by core/main.py.
vortex_link = VortexLink()
