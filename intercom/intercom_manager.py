"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        intercom/intercom_manager.py
Purpose:     Peer-to-peer "Drop In" intercom between River Vortex units in the
             home. A single UDP socket per unit carries both call-signaling
             control messages (JSON "call_request" / "call_accept" /
             "call_decline" / "call_busy" / "call_end") and raw PCM audio
             frames once a call is active. See core/intercom_api.py for the
             REST surface (/api/vortex/v1/intercom) that River Song's voice
             intent handlers ("call the kitchen", "answer", "hang up") drive.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import json
import logging
import socket
from typing import Any, Dict, Optional

from core.config import config
from core.constants import (
    INTERCOM_MAX_CALL_DURATION_SECONDS,
    INTERCOM_PORT,
    INTERCOM_RING_TIMEOUT_SECONDS,
)
from core.ws_hub import ws_hub

logger = logging.getLogger(__name__)


class IntercomState:
    """Intercom call states."""
    IDLE = "idle"
    CALLING = "calling"
    RINGING = "ringing"
    ACTIVE = "active"


class IntercomError(Exception):
    """Raised for invalid intercom operations (e.g., answering with no incoming call)."""


# UDP packet framing — a single-byte prefix distinguishes JSON call-signaling
# messages from raw PCM audio frames on the shared intercom socket/port.
_PACKET_CONTROL = b"\x01"
_PACKET_AUDIO = b"\x02"


class IntercomManager:
    """
    Manages peer-to-peer "Drop In" audio intercom between River Vortex units.

    Architecture:
    - Unit discovery is handled by UnitDiscovery (unit_discovery.py)
    - Call signaling AND audio frames share a single UDP socket, distinguished
      by a one-byte packet prefix (_PACKET_CONTROL / _PACKET_AUDIO)
    - Each call is a direct peer-to-peer connection (no relay server)
    - Maximum call duration and unanswered-ring duration are enforced by
      timeout tasks

    Usage:
        manager = IntercomManager(microphone=mic, speaker=speaker)
        await manager.start()
        await manager.call("vortex-bedroom-01")
        ...
        await manager.end_call()
    """

    def __init__(self, microphone: Optional[Any] = None, speaker: Optional[Any] = None) -> None:
        """
        Initialize IntercomManager.

        Args:
            microphone: Optional audio.microphone.Microphone used to capture
                        outgoing audio while a call is ACTIVE. If None, no
                        audio is sent (signaling-only).
            speaker:    Optional audio.speaker.Speaker used to play incoming
                        audio frames via play_raw(). If None, incoming audio
                        is discarded.
        """
        self._state: str = IntercomState.IDLE
        self._active_peer: Optional[str] = None
        self._active_peer_ip: Optional[str] = None
        self._active_peer_name: Optional[str] = None
        self._active_peer_location: Optional[str] = None

        self._microphone = microphone
        self._speaker = speaker

        self._unit_id: str = config.get("unit_id", "vortex-unset")
        self._unit_name: str = config.get("unit_name", "River Vortex")
        self._location: str = config.get("location", "Unknown")

        self._call_timeout_task: Optional[asyncio.Task] = None
        self._ring_timeout_task: Optional[asyncio.Task] = None
        self._send_task: Optional[asyncio.Task] = None
        self._listen_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._port: int = config.get("intercom_port", INTERCOM_PORT)

        # UDP socket for call signaling + audio transport
        self._udp_socket: Optional[socket.socket] = None

        # Callbacks
        self._on_incoming_call = None
        self._on_call_ended = None

    async def start(self) -> None:
        """Start the intercom manager, open the UDP socket, and begin listening."""
        self._running = True
        self._open_udp_socket()
        self._listen_task = asyncio.create_task(self._listen_loop(), name="intercom-listen")
        logger.info("IntercomManager started on port %d.", self._port)

    async def stop(self) -> None:
        """Stop the intercom manager, end any active call, and close the socket."""
        self._running = False
        if self._state != IntercomState.IDLE:
            await self.end_call()
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None
        self._close_udp_socket()
        logger.info("IntercomManager stopped.")

    # ─────────────────────────────────────────────────────────────────────────
    # Call Control
    # ─────────────────────────────────────────────────────────────────────────

    async def call(self, peer_unit_id: str) -> Dict[str, Any]:
        """
        Place an intercom "Drop In" call to another Vortex unit.

        Args:
            peer_unit_id: The unit ID of the target Vortex unit (see
                          UnitDiscovery.get_peers()).

        Returns:
            The new intercom state (see get_state()).

        Raises:
            IntercomError: If a call is already in progress, or the peer
                           cannot be found on the local network.
        """
        if self._state != IntercomState.IDLE:
            raise IntercomError(f"Cannot place call — intercom is already {self._state}.")

        from intercom.unit_discovery import UnitDiscovery
        peer_info = UnitDiscovery().get_peer(peer_unit_id)
        if not peer_info:
            raise IntercomError(f"Peer unit '{peer_unit_id}' not found on network.")

        self._set_active_peer(peer_info)
        self._state = IntercomState.CALLING
        logger.info("Calling %s ('%s') at %s...", peer_unit_id, self._active_peer_location, self._active_peer_ip)

        await self._send_control("call_request", self._active_peer_ip)
        self._ring_timeout_task = asyncio.create_task(
            self._ring_timeout_handler(), name="intercom-ring-timeout"
        )
        await self._broadcast()
        return self.get_state()

    async def answer(self) -> Dict[str, Any]:
        """
        Answer an incoming "Drop In" call.

        Returns:
            The new (ACTIVE) intercom state.

        Raises:
            IntercomError: If there is no incoming call to answer.
        """
        if self._state != IntercomState.RINGING:
            raise IntercomError("No incoming call to answer.")

        self._cancel_task("_ring_timeout_task")
        await self._send_control("call_accept", self._active_peer_ip)
        await self._activate_call()
        return self.get_state()

    async def decline(self) -> Dict[str, Any]:
        """
        Decline an incoming "Drop In" call.

        Returns:
            The new (IDLE) intercom state.

        Raises:
            IntercomError: If there is no incoming call to decline.
        """
        if self._state != IntercomState.RINGING:
            raise IntercomError("No incoming call to decline.")

        await self._send_control("call_decline", self._active_peer_ip)
        await self._reset_to_idle()
        return self.get_state()

    async def end_call(self) -> Dict[str, Any]:
        """
        End the current call (hang up), or no-op if already idle.

        Returns:
            The new (IDLE) intercom state.
        """
        if self._state == IntercomState.IDLE:
            return self.get_state()

        logger.info("Ending intercom call with %s.", self._active_peer)
        if self._active_peer_ip:
            await self._send_control("call_end", self._active_peer_ip)
        await self._reset_to_idle()
        return self.get_state()

    def on_incoming_call(self, callback) -> None:
        """
        Register a callback for incoming intercom calls.

        Args:
            callback: Called with (peer_unit_id: str) when a call arrives.
        """
        self._on_incoming_call = callback

    def on_call_ended(self, callback) -> None:
        """
        Register a callback for when a call ends.

        Args:
            callback: Called with no arguments when the call ends.
        """
        self._on_call_ended = callback

    @property
    def state(self) -> str:
        """Return the current intercom state."""
        return self._state

    def get_state(self) -> Dict[str, Any]:
        """
        Return the current intercom state.

        Returns:
            Dict with `state` (one of IntercomState) and `peer` — either None
            or a dict with `unit_id`, `unit_name`, `location` for the unit
            this device is calling, ringing from, or actively talking to.
        """
        peer = None
        if self._active_peer:
            peer = {
                "unit_id": self._active_peer,
                "unit_name": self._active_peer_name,
                "location": self._active_peer_location,
            }
        return {"state": self._state, "peer": peer}

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    def _set_active_peer(self, peer_info: Dict[str, Any]) -> None:
        """Record the peer this unit is calling, ringing from, or talking to."""
        self._active_peer = peer_info.get("unit_id")
        self._active_peer_ip = peer_info.get("ip")
        self._active_peer_name = peer_info.get("unit_name")
        self._active_peer_location = peer_info.get("location")

    def _cancel_task(self, attr_name: str) -> None:
        """Cancel and clear the asyncio.Task stored on the named attribute, if any."""
        task = getattr(self, attr_name, None)
        if task:
            task.cancel()
            setattr(self, attr_name, None)

    async def _activate_call(self) -> None:
        """Transition to ACTIVE, start the audio send loop, and arm the call timeout."""
        self._state = IntercomState.ACTIVE
        self._start_audio_stream()
        self._call_timeout_task = asyncio.create_task(
            self._call_timeout_handler(), name="intercom-call-timeout"
        )
        await self._broadcast()
        logger.info("Intercom call active with %s.", self._active_peer)

    async def _reset_to_idle(self) -> None:
        """Tear down the current call (if any) and return to IDLE."""
        self._cancel_task("_call_timeout_task")
        self._cancel_task("_ring_timeout_task")
        self._cancel_task("_send_task")

        if self._speaker:
            try:
                self._speaker.stop_raw()
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("Error stopping raw audio playback: %s", exc)

        ended_peer = self._active_peer
        self._state = IntercomState.IDLE
        self._active_peer = None
        self._active_peer_ip = None
        self._active_peer_name = None
        self._active_peer_location = None

        await self._broadcast()

        if ended_peer and self._on_call_ended:
            try:
                self._on_call_ended()
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("on_call_ended callback failed: %s", exc)

    async def _broadcast(self) -> None:
        await ws_hub.broadcast({"type": "intercom_update", "intercom": self.get_state()})

    def _open_udp_socket(self) -> None:
        """Open the UDP socket used for call signaling and audio transport."""
        try:
            self._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._udp_socket.bind(("0.0.0.0", self._port))
            self._udp_socket.setblocking(False)
            logger.debug("Intercom UDP socket bound to port %d.", self._port)
        except OSError as exc:
            logger.error("Failed to open intercom UDP socket: %s", exc)

    def _close_udp_socket(self) -> None:
        """Close the UDP socket."""
        if self._udp_socket:
            try:
                self._udp_socket.close()
            except Exception:  # pylint: disable=broad-except
                pass
            self._udp_socket = None

    async def _send_control(self, msg_type: str, peer_ip: Optional[str]) -> None:
        """Send a JSON call-signaling packet to `peer_ip` on the intercom port."""
        if not self._udp_socket or not peer_ip:
            return
        payload = _PACKET_CONTROL + json.dumps({
            "type": msg_type,
            "unit_id": self._unit_id,
            "unit_name": self._unit_name,
            "location": self._location,
        }).encode("utf-8")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: self._udp_socket.sendto(payload, (peer_ip, self._port))
            )
        except OSError as exc:
            logger.debug("Failed to send intercom '%s' message: %s", msg_type, exc)

    async def _listen_loop(self) -> None:
        """Persistently listen for incoming control messages and audio frames."""
        loop = asyncio.get_event_loop()
        logger.debug("Intercom listen loop started.")
        try:
            while self._running:
                try:
                    data, addr = await loop.run_in_executor(None, self._recv_nonblocking)
                    if data:
                        self._handle_packet(data, addr[0])
                except Exception as exc:  # pylint: disable=broad-except
                    logger.debug("Intercom listen loop error: %s", exc)
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            pass

    def _recv_nonblocking(self):
        """Attempt a non-blocking receive from the intercom UDP socket."""
        if not self._udp_socket:
            return None, None
        try:
            return self._udp_socket.recvfrom(4096)
        except (BlockingIOError, OSError):
            return None, None

    def _handle_packet(self, data: bytes, sender_ip: str) -> None:
        """Dispatch a received UDP packet based on its framing prefix byte."""
        if not data:
            return
        marker, payload = data[:1], data[1:]
        if marker == _PACKET_CONTROL:
            self._handle_control_message(payload, sender_ip)
        elif marker == _PACKET_AUDIO:
            self._handle_audio_frame(payload, sender_ip)

    def _handle_control_message(self, payload: bytes, sender_ip: str) -> None:
        """Process a received call-signaling JSON message."""
        try:
            msg = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        msg_type = msg.get("type")
        peer_unit_id = msg.get("unit_id")

        if msg_type == "call_request":
            if self._state != IntercomState.IDLE:
                asyncio.create_task(self._send_control("call_busy", sender_ip))
                return
            self._set_active_peer({
                "unit_id": peer_unit_id,
                "unit_name": msg.get("unit_name", peer_unit_id),
                "location": msg.get("location", "Unknown"),
                "ip": sender_ip,
            })
            self._state = IntercomState.RINGING
            self._ring_timeout_task = asyncio.create_task(
                self._ring_timeout_handler(), name="intercom-ring-timeout"
            )
            asyncio.create_task(self._broadcast())
            if self._on_incoming_call:
                try:
                    self._on_incoming_call(peer_unit_id)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("on_incoming_call callback failed: %s", exc)

        elif msg_type == "call_accept":
            if self._state == IntercomState.CALLING and peer_unit_id == self._active_peer:
                self._cancel_task("_ring_timeout_task")
                asyncio.create_task(self._activate_call())

        elif msg_type in ("call_decline", "call_busy"):
            if self._state == IntercomState.CALLING and peer_unit_id == self._active_peer:
                asyncio.create_task(self._reset_to_idle())

        elif msg_type == "call_end":
            if self._active_peer == peer_unit_id and self._state != IntercomState.IDLE:
                asyncio.create_task(self._reset_to_idle())

    def _handle_audio_frame(self, frame: bytes, sender_ip: str) -> None:
        """Play an incoming raw PCM audio frame from the active call peer."""
        if self._state != IntercomState.ACTIVE or sender_ip != self._active_peer_ip:
            return
        if self._speaker:
            try:
                self._speaker.play_raw(frame)
            except Exception as exc:  # pylint: disable=broad-except
                logger.debug("Failed to play intercom audio frame: %s", exc)

    def _start_audio_stream(self) -> None:
        """Start the outgoing audio capture/send task for the active call."""
        self._send_task = asyncio.create_task(self._audio_send_loop(), name="intercom-send")

    async def _audio_send_loop(self) -> None:
        """Capture microphone audio and send it to the active peer via UDP."""
        logger.debug("Intercom audio send loop started.")
        loop = asyncio.get_event_loop()
        try:
            while self._state == IntercomState.ACTIVE:
                if (
                    self._microphone
                    and self._microphone.is_open
                    and self._udp_socket
                    and self._active_peer_ip
                ):
                    try:
                        frame = await loop.run_in_executor(None, self._microphone.read_frame)
                        await loop.run_in_executor(
                            None,
                            lambda f=frame: self._udp_socket.sendto(
                                _PACKET_AUDIO + f, (self._active_peer_ip, self._port)
                            ),
                        )
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.debug("Intercom audio send error: %s", exc)
                        await asyncio.sleep(0.02)
                else:
                    await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            pass

    async def _ring_timeout_handler(self) -> None:
        """End the call if it is not answered/accepted within the ring timeout."""
        try:
            await asyncio.sleep(INTERCOM_RING_TIMEOUT_SECONDS)
            logger.info("Intercom call with %s timed out unanswered.", self._active_peer)
            if self._active_peer_ip:
                if self._state == IntercomState.CALLING:
                    await self._send_control("call_end", self._active_peer_ip)
                elif self._state == IntercomState.RINGING:
                    await self._send_control("call_decline", self._active_peer_ip)
            await self._reset_to_idle()
        except asyncio.CancelledError:
            pass

    async def _call_timeout_handler(self) -> None:
        """End the call after the maximum duration."""
        try:
            await asyncio.sleep(INTERCOM_MAX_CALL_DURATION_SECONDS)
            logger.info("Intercom call reached maximum duration — ending.")
            await self.end_call()
        except asyncio.CancelledError:
            pass
