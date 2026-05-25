"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        intercom/unit_discovery.py
Purpose:     Multicast-based discovery of other River Vortex units on the
             local network. Broadcasts unit presence, listens for peer
             announcements, and maintains a live registry of available units
             for the intercom system.
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
import struct
import time
from typing import Dict, List, Optional

from core.config import config
from core.constants import (
    INTERCOM_DISCOVERY_INTERVAL_SECONDS,
    INTERCOM_DISCOVERY_PORT,
    INTERCOM_HEARTBEAT_INTERVAL_SECONDS,
    INTERCOM_MULTICAST_GROUP,
    INTERCOM_PEER_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


class UnitDiscovery:
    """
    Discovers other River Vortex units on the local network via UDP multicast.

    Each unit broadcasts a heartbeat every INTERCOM_HEARTBEAT_INTERVAL_SECONDS
    seconds. Units that have not sent a heartbeat within INTERCOM_PEER_TIMEOUT_SECONDS
    are removed from the registry.

    The discovery registry is used by IntercomManager to resolve unit IDs
    to IP addresses for call routing.
    """

    # Class-level peer registry shared across instances
    _peers: Dict[str, dict] = {}

    def __init__(self) -> None:
        """Initialize UnitDiscovery."""
        self._unit_id: str = config.get("unit_id", "vortex-unset")
        self._unit_name: str = config.get("unit_name", "River Vortex")
        self._location: str = config.get("location", "Unknown")
        self._running: bool = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._listen_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._mcast_socket: Optional[socket.socket] = None

    async def start(self) -> None:
        """Start broadcasting presence and listening for peers."""
        self._running = True
        self._open_multicast_socket()
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name="unit-discovery-heartbeat"
        )
        self._listen_task = asyncio.create_task(
            self._listen_loop(), name="unit-discovery-listen"
        )
        self._cleanup_task = asyncio.create_task(
            self._cleanup_loop(), name="unit-discovery-cleanup"
        )
        logger.info(
            "UnitDiscovery started. Broadcasting as '%s' (%s).",
            self._unit_name,
            self._unit_id,
        )

    async def stop(self) -> None:
        """Stop discovery and close the multicast socket."""
        self._running = False
        for task in (self._heartbeat_task, self._listen_task, self._cleanup_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._mcast_socket:
            self._mcast_socket.close()
        logger.info("UnitDiscovery stopped.")

    def get_peers(self) -> List[dict]:
        """
        Return all currently known peer units.

        Returns:
            List of peer info dicts with unit_id, unit_name, location, ip, last_seen.
        """
        return list(UnitDiscovery._peers.values())

    def get_peer(self, unit_id: str) -> Optional[dict]:
        """
        Look up a specific peer by unit ID.

        Args:
            unit_id: The unit ID to look up.

        Returns:
            Peer info dict, or None if not found.
        """
        return UnitDiscovery._peers.get(unit_id)

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    def _open_multicast_socket(self) -> None:
        """Open and configure the UDP multicast socket."""
        try:
            self._mcast_socket = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
            )
            self._mcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._mcast_socket.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_MULTICAST_TTL,
                2,
            )
            self._mcast_socket.bind(("", INTERCOM_DISCOVERY_PORT))

            # Join the multicast group
            group = socket.inet_aton(INTERCOM_MULTICAST_GROUP)
            mreq = struct.pack("4sL", group, socket.INADDR_ANY)
            self._mcast_socket.setsockopt(
                socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq
            )
            self._mcast_socket.setblocking(False)
            logger.debug(
                "Multicast socket joined group %s on port %d.",
                INTERCOM_MULTICAST_GROUP,
                INTERCOM_DISCOVERY_PORT,
            )
        except OSError as exc:
            logger.error("Failed to open multicast socket: %s", exc)

    async def _heartbeat_loop(self) -> None:
        """Broadcast this unit's presence at regular intervals."""
        while self._running:
            await self._broadcast_presence()
            await asyncio.sleep(INTERCOM_HEARTBEAT_INTERVAL_SECONDS)

    async def _broadcast_presence(self) -> None:
        """Send a UDP multicast announcement with this unit's info."""
        if not self._mcast_socket:
            return
        payload = json.dumps({
            "type": "vortex_presence",
            "unit_id": self._unit_id,
            "unit_name": self._unit_name,
            "location": self._location,
            "intercom_port": config.get("intercom_port", 5005),
        }).encode("utf-8")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._mcast_socket.sendto(
                    payload, (INTERCOM_MULTICAST_GROUP, INTERCOM_DISCOVERY_PORT)
                ),
            )
        except Exception as exc:
            logger.debug("Presence broadcast error: %s", exc)

    async def _listen_loop(self) -> None:
        """Listen for presence announcements from other units."""
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                data, addr = await loop.run_in_executor(
                    None, self._recv_nonblocking
                )
                if data:
                    self._handle_announcement(data, addr[0])
            except Exception:  # pylint: disable=broad-except
                pass
            await asyncio.sleep(0.1)

    def _recv_nonblocking(self):
        """Attempt a non-blocking receive from the multicast socket."""
        if not self._mcast_socket:
            return None, None
        try:
            return self._mcast_socket.recvfrom(1024)
        except BlockingIOError:
            return None, None

    def _handle_announcement(self, data: bytes, sender_ip: str) -> None:
        """
        Process a received presence announcement.

        Args:
            data:      Raw UDP payload bytes.
            sender_ip: IP address of the sending unit.
        """
        try:
            msg = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        if msg.get("type") != "vortex_presence":
            return

        unit_id = msg.get("unit_id")
        if not unit_id or unit_id == self._unit_id:
            return  # Ignore our own broadcasts

        UnitDiscovery._peers[unit_id] = {
            "unit_id": unit_id,
            "unit_name": msg.get("unit_name", unit_id),
            "location": msg.get("location", "Unknown"),
            "ip": sender_ip,
            "intercom_port": msg.get("intercom_port", INTERCOM_DISCOVERY_PORT),
            "last_seen": time.monotonic(),
        }
        logger.debug("Discovered peer: %s at %s (%s)", unit_id, sender_ip, msg.get("location"))

    async def _cleanup_loop(self) -> None:
        """Remove peers that have not sent a heartbeat recently."""
        while self._running:
            now = time.monotonic()
            stale = [
                uid for uid, info in UnitDiscovery._peers.items()
                if now - info.get("last_seen", 0) > INTERCOM_PEER_TIMEOUT_SECONDS
            ]
            for uid in stale:
                del UnitDiscovery._peers[uid]
                logger.info("Peer '%s' timed out and was removed from registry.", uid)
            await asyncio.sleep(INTERCOM_DISCOVERY_INTERVAL_SECONDS)
