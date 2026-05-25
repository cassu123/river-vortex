"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        intercom/intercom_manager.py
Purpose:     Peer-to-peer intercom system between River Vortex units in the
             home. Manages call initiation, audio streaming, and call teardown.
             Uses UDP for low-latency audio transport between units discovered
             via multicast on the local network.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import logging
import socket
import struct
from typing import Dict, Optional

from core.config import config
from core.constants import (
    INTERCOM_AUDIO_CHANNELS,
    INTERCOM_AUDIO_SAMPLE_RATE,
    INTERCOM_MAX_CALL_DURATION_SECONDS,
    INTERCOM_PORT,
)

logger = logging.getLogger(__name__)


class IntercomState:
    """Intercom call states."""
    IDLE = "idle"
    CALLING = "calling"
    RINGING = "ringing"
    ACTIVE = "active"


class IntercomManager:
    """
    Manages peer-to-peer audio intercom between River Vortex units.

    Architecture:
    - Unit discovery is handled by UnitDiscovery (unit_discovery.py)
    - Audio is streamed over UDP for low latency
    - Each call is a direct peer-to-peer connection (no relay server)
    - Maximum call duration is enforced by a timeout task

    Usage:
        manager = IntercomManager()
        await manager.start()
        await manager.call("vortex-bedroom-01")
    """

    def __init__(self) -> None:
        """Initialize IntercomManager."""
        self._state: str = IntercomState.IDLE
        self._active_peer: Optional[str] = None
        self._active_peer_ip: Optional[str] = None
        self._call_timeout_task: Optional[asyncio.Task] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._send_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._port: int = config.get("intercom_port", INTERCOM_PORT)

        # UDP socket for audio transport
        self._udp_socket: Optional[socket.socket] = None

        # Callbacks
        self._on_incoming_call = None
        self._on_call_ended = None

    async def start(self) -> None:
        """Start the intercom manager and open the UDP socket."""
        self._running = True
        self._open_udp_socket()
        logger.info("IntercomManager started on port %d.", self._port)

    async def stop(self) -> None:
        """Stop the intercom manager and close all connections."""
        self._running = False
        if self._state == IntercomState.ACTIVE:
            await self.end_call()
        self._close_udp_socket()
        logger.info("IntercomManager stopped.")

    # ─────────────────────────────────────────────────────────────────────────
    # Call Control
    # ─────────────────────────────────────────────────────────────────────────

    async def call(self, peer_unit_id: str) -> bool:
        """
        Initiate an intercom call to another Vortex unit.

        Args:
            peer_unit_id: The unit ID of the target Vortex unit.

        Returns:
            True if the call was accepted, False otherwise.
        """
        if self._state != IntercomState.IDLE:
            logger.warning("Cannot initiate call — intercom is %s.", self._state)
            return False

        from intercom.unit_discovery import UnitDiscovery
        discovery = UnitDiscovery()
        peer_info = discovery.get_peer(peer_unit_id)

        if not peer_info:
            logger.error("Peer unit '%s' not found on network.", peer_unit_id)
            return False

        self._active_peer = peer_unit_id
        self._active_peer_ip = peer_info.get("ip")
        self._state = IntercomState.CALLING

        logger.info("Calling %s at %s...", peer_unit_id, self._active_peer_ip)

        # Send call request packet
        success = await self._send_call_request()
        if success:
            self._state = IntercomState.ACTIVE
            await self._start_audio_stream()
            self._call_timeout_task = asyncio.create_task(
                self._call_timeout_handler(), name="intercom-timeout"
            )
            logger.info("Intercom call active with %s.", peer_unit_id)
        else:
            self._state = IntercomState.IDLE
            self._active_peer = None
            self._active_peer_ip = None

        return success

    async def end_call(self) -> None:
        """End the active intercom call."""
        if self._state == IntercomState.IDLE:
            return

        logger.info("Ending intercom call with %s.", self._active_peer)

        if self._call_timeout_task:
            self._call_timeout_task.cancel()
        if self._send_task:
            self._send_task.cancel()
        if self._receive_task:
            self._receive_task.cancel()

        self._state = IntercomState.IDLE
        self._active_peer = None
        self._active_peer_ip = None

        if self._on_call_ended:
            self._on_call_ended()

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

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    def _open_udp_socket(self) -> None:
        """Open the UDP socket for audio transport."""
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

    async def _send_call_request(self) -> bool:
        """
        Send a call request packet to the peer and wait for acceptance.

        Returns:
            True if the peer accepted the call.
        """
        # Simplified call signaling — production would use a proper
        # signaling protocol (e.g., SIP or a custom WebSocket handshake)
        logger.debug("Sending call request to %s:%d", self._active_peer_ip, self._port)
        # Placeholder: actual implementation sends a UDP control packet
        # and waits for an ACK within a timeout
        await asyncio.sleep(0.1)  # Simulate network round-trip
        return True

    async def _start_audio_stream(self) -> None:
        """Start the bidirectional audio stream tasks."""
        self._send_task = asyncio.create_task(
            self._audio_send_loop(), name="intercom-send"
        )
        self._receive_task = asyncio.create_task(
            self._audio_receive_loop(), name="intercom-receive"
        )

    async def _audio_send_loop(self) -> None:
        """Capture microphone audio and send to peer via UDP."""
        logger.debug("Intercom audio send loop started.")
        # Placeholder: reads from microphone and sends UDP packets to peer
        try:
            while self._state == IntercomState.ACTIVE:
                await asyncio.sleep(0.02)  # 20ms audio frames
        except asyncio.CancelledError:
            pass

    async def _audio_receive_loop(self) -> None:
        """Receive audio from peer via UDP and play through speaker."""
        logger.debug("Intercom audio receive loop started.")
        # Placeholder: receives UDP packets and plays through speaker
        try:
            while self._state == IntercomState.ACTIVE:
                await asyncio.sleep(0.02)
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
