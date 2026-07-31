"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        audio/media_player.py
Purpose:     Streaming media playback on the unit — music, radio, podcasts.

             Distinct from audio/speaker.py, which plays short WAV blobs
             (chimes and TTS) and blocks while it does. Music is long-running,
             needs transport controls, and has to duck out of the way when
             River speaks or a timer fires, so it gets its own player.

             Playback runs in mpv as a child process, controlled over its JSON
             IPC socket. mpv is one static binary, handles HTTP streams and
             redirects, and uses the Pi's hardware decoder — decoding a stream
             in Python on a Pi 4 is not viable.

             River Song resolves "play something by Fleetwood Mac" into a
             stream URL and metadata and hands both here. Vortex does not know
             what YouTube Music is; it plays a URL and shows a title.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import json
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional

from core.constants import (
    MEDIA_DUCK_VOLUME_LEVEL,
    MEDIA_IPC_TIMEOUT_SECONDS,
    MEDIA_STARTUP_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


class MediaPlayerError(Exception):
    """Raised when playback cannot be started or controlled."""


class PlaybackState:
    """The player's transport state, as reported to the UI."""
    IDLE = "idle"
    LOADING = "loading"
    PLAYING = "playing"
    PAUSED = "paused"


class MediaPlayer:
    """
    Streaming audio playback with transport controls and ducking.

    Usage:
        player = MediaPlayer(on_change=broadcast_fn)
        await player.start()
        await player.play(url, {"title": "Dreams", "artist": "Fleetwood Mac"})
        await player.duck()      # River is about to speak
        await player.unduck()

    Args:
        on_change: Optional async callable invoked with get_state() whenever
                   the transport state changes, so the UI can follow along.
    """

    def __init__(self, on_change=None) -> None:
        """Initialize. Does not launch mpv until start()."""
        self._on_change = on_change
        self._proc: Optional[subprocess.Popen] = None
        self._socket_path: Optional[str] = None
        self._available: bool = shutil.which("mpv") is not None

        self._state: str = PlaybackState.IDLE
        self._now_playing: Dict[str, Any] = {}
        self._queue: List[Dict[str, Any]] = []
        self._queue_index: int = -1
        self._volume: int = 80
        self._ducked: bool = False
        self._started_at: float = 0.0

        if not self._available:
            logger.warning(
                "mpv is not installed — media playback is disabled. "
                "Install it with: sudo apt install mpv"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Launch mpv in idle mode, ready to accept a stream.

        Starting it once and keeping it resident avoids a process spawn on
        every track, which on a Pi is the difference between instant and a
        second of silence.
        """
        if not self._available or self._proc is not None:
            return

        self._socket_path = os.path.join(
            tempfile.gettempdir(), f"vortex-mpv-{os.getpid()}.sock"
        )
        try:
            self._proc = subprocess.Popen(
                [
                    "mpv",
                    "--idle=yes",
                    "--no-video",
                    "--no-terminal",
                    f"--input-ipc-server={self._socket_path}",
                    f"--volume={self._volume}",
                    # Streams over wifi stall; a generous cache rides it out.
                    "--cache=yes",
                    "--cache-secs=30",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.error("Could not launch mpv: %s", exc)
            self._proc = None
            self._available = False
            return

        # Wait for the IPC socket to appear before anyone tries to use it.
        deadline = time.monotonic() + MEDIA_STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if os.path.exists(self._socket_path):
                logger.info("MediaPlayer ready (mpv).")
                return
            await asyncio.sleep(0.1)

        logger.error("mpv did not create its IPC socket in time.")

    async def stop(self) -> None:
        """Stop playback and shut mpv down."""
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=3)
        except Exception:  # pylint: disable=broad-except
            try:
                self._proc.kill()
            except Exception:  # pylint: disable=broad-except
                pass
        self._proc = None

        if self._socket_path and os.path.exists(self._socket_path):
            try:
                os.unlink(self._socket_path)
            except OSError:
                pass

        self._state = PlaybackState.IDLE
        logger.info("MediaPlayer stopped.")

    @property
    def available(self) -> bool:
        """True if playback is possible on this unit."""
        return self._available and self._proc is not None

    # ─────────────────────────────────────────────────────────────────────────
    # Transport
    # ─────────────────────────────────────────────────────────────────────────

    async def play(self, url: str, metadata: Optional[Dict[str, Any]] = None,
                   queue: Optional[List[Dict[str, Any]]] = None) -> None:
        """
        Start playing a stream.

        Args:
            url:      Direct stream URL, already resolved by River Song.
            metadata: Display fields — title, artist, album, artwork_url.
            queue:    Optional upcoming tracks, each {url, title, artist, ...},
                      enabling next/previous without another round trip.

        Raises:
            MediaPlayerError: If playback is unavailable on this unit.
        """
        if not self.available:
            raise MediaPlayerError("Media playback is unavailable on this unit.")
        if not url:
            raise MediaPlayerError("Cannot play an empty URL.")

        self._now_playing = dict(metadata or {})
        self._now_playing["url"] = url
        if queue is not None:
            self._queue = list(queue)
            self._queue_index = 0
        self._started_at = time.monotonic()

        self._state = PlaybackState.LOADING
        await self._notify()

        await self._command(["loadfile", url, "replace"])
        await self._command(["set_property", "pause", False])

        self._state = PlaybackState.PLAYING
        logger.info("Playing: %s — %s",
                    self._now_playing.get("artist", "?"),
                    self._now_playing.get("title", url[:60]))
        await self._notify()

    async def pause(self) -> None:
        """Pause playback, keeping position."""
        if self._state != PlaybackState.PLAYING:
            return
        await self._command(["set_property", "pause", True])
        self._state = PlaybackState.PAUSED
        await self._notify()

    async def resume(self) -> None:
        """Resume from pause."""
        if self._state != PlaybackState.PAUSED:
            return
        await self._command(["set_property", "pause", False])
        self._state = PlaybackState.PLAYING
        await self._notify()

    async def toggle(self) -> None:
        """Pause if playing, resume if paused. What the play/pause button does."""
        if self._state == PlaybackState.PLAYING:
            await self.pause()
        elif self._state == PlaybackState.PAUSED:
            await self.resume()

    async def stop_playback(self) -> None:
        """Stop and clear what is playing, without shutting mpv down."""
        await self._command(["stop"])
        self._state = PlaybackState.IDLE
        self._now_playing = {}
        self._queue = []
        self._queue_index = -1
        await self._notify()

    async def next_track(self) -> bool:
        """
        Skip to the next queued track.

        Returns:
            True if a track was started, False at the end of the queue.
        """
        if self._queue_index < 0 or self._queue_index + 1 >= len(self._queue):
            return False
        self._queue_index += 1
        track = self._queue[self._queue_index]
        await self.play(track.get("url", ""), track)
        return True

    async def previous_track(self) -> bool:
        """
        Go back one track.

        Returns:
            True if a track was started, False at the start of the queue.
        """
        if self._queue_index <= 0:
            return False
        self._queue_index -= 1
        track = self._queue[self._queue_index]
        await self.play(track.get("url", ""), track)
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Volume & ducking
    # ─────────────────────────────────────────────────────────────────────────

    async def set_volume(self, level: int) -> None:
        """
        Set playback volume.

        Args:
            level: 0–100.
        """
        self._volume = max(0, min(100, int(level)))
        if not self._ducked:
            await self._command(["set_property", "volume", self._volume])
        await self._notify()

    async def duck(self) -> None:
        """
        Drop the volume so River, a timer, or an announcement is audible over it.

        Idempotent — two overlapping things ducking will not stack down to
        silence, and the first unduck does not restore while the second is
        still speaking, because unduck simply returns to the stored level.
        """
        if self._ducked:
            return
        self._ducked = True
        ducked_level = int(self._volume * MEDIA_DUCK_VOLUME_LEVEL)
        await self._command(["set_property", "volume", ducked_level])
        logger.debug("Media ducked to %d%%.", ducked_level)

    async def unduck(self) -> None:
        """Restore the volume after ducking."""
        if not self._ducked:
            return
        self._ducked = False
        await self._command(["set_property", "volume", self._volume])
        logger.debug("Media restored to %d%%.", self._volume)

    # ─────────────────────────────────────────────────────────────────────────
    # State
    # ─────────────────────────────────────────────────────────────────────────

    def get_state(self) -> Dict[str, Any]:
        """
        Return the current transport state for the UI.

        Returns:
            Dict with state, now_playing, queue position, volume and
            availability.
        """
        return {
            "state": self._state,
            "available": self.available,
            "now_playing": self._now_playing,
            "volume": self._volume,
            "ducked": self._ducked,
            "queue_length": len(self._queue),
            "queue_index": self._queue_index,
            "has_next": 0 <= self._queue_index < len(self._queue) - 1,
            "has_previous": self._queue_index > 0,
            "elapsed_seconds": (
                int(time.monotonic() - self._started_at)
                if self._state == PlaybackState.PLAYING else 0
            ),
        }

    def is_playing(self) -> bool:
        """True if audio is actively coming out of the speaker."""
        return self._state == PlaybackState.PLAYING

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    async def _command(self, command: List[Any]) -> Optional[Dict[str, Any]]:
        """
        Send one JSON IPC command to mpv.

        Args:
            command: mpv command, e.g. ["set_property", "volume", 50].

        Returns:
            The parsed reply, or None if mpv is unreachable. Failures are
            logged rather than raised — a stuck socket must not take down the
            caller, which is usually a voice command or a screen tap.
        """
        if not self._socket_path or not os.path.exists(self._socket_path):
            return None

        payload = json.dumps({"command": command}).encode() + b"\n"

        def _send() -> Optional[Dict[str, Any]]:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(MEDIA_IPC_TIMEOUT_SECONDS)
                    sock.connect(self._socket_path)
                    sock.sendall(payload)
                    raw = sock.recv(4096)
                for line in raw.splitlines():
                    if not line.strip():
                        continue
                    reply = json.loads(line)
                    # mpv also emits async events on this socket; only a reply
                    # to our command carries "error".
                    if "error" in reply:
                        return reply
            except (OSError, ValueError) as exc:
                logger.debug("mpv IPC failed for %s: %s", command[0], exc)
            return None

        return await asyncio.to_thread(_send)

    async def _notify(self) -> None:
        """Push the transport state to whoever is listening."""
        if self._on_change is None:
            return
        try:
            await self._on_change(self.get_state())
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Media state notification failed: %s", exc)
