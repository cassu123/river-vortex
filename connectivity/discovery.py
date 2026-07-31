"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        connectivity/discovery.py
Purpose:     Advertises this unit on the local network via mDNS/Zeroconf so
             the River Song app/browser can find it during setup — and so
             River Song can keep track of paired units afterwards. Failures
             here are non-fatal: if Zeroconf is unavailable, River Vortex
             continues to run, it just won't be auto-discoverable (the user
             can still enter the unit's IP address manually).
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-11
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
import re
import socket

from core.config import config
from core.constants import (
    BACKEND_PORT,
    MDNS_SERVICE_TYPE,
    RIVER_SONG_SETUP_BASE,
    VERSION,
)

logger = logging.getLogger(__name__)


def _local_ip_address() -> str:
    """
    Best-effort guess at this unit's LAN IP address.

    Opens a UDP socket toward a public address (no packets are actually
    sent) purely to ask the OS which local interface/IP would be used.
    Falls back to loopback if that fails (e.g., no network at all).

    Returns:
        The unit's LAN IP address as a string.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _service_name() -> str:
    """Build an mDNS-safe service instance name from the unit's identity."""
    raw = f"{config.get('unit_name', 'River Vortex')}-{config.get('unit_id', 'vortex-unset')}"
    safe = re.sub(r"[^A-Za-z0-9-]+", "-", raw).strip("-")
    return f"{safe}.{MDNS_SERVICE_TYPE}"


class DiscoveryService:
    """
    Registers (and unregisters) this unit's mDNS advertisement.

    The advertised TXT record includes the unit's id/name/location, version,
    and pairing status so the River Song app can list nearby units and tell
    at a glance which ones still need setup.
    """

    def __init__(self) -> None:
        """Initialize with no active Zeroconf registration."""
        self._aiozc = None
        self._service_info = None

    async def start(self) -> None:
        """
        Build and register the mDNS service announcement.

        Any failure (missing dependency, no network, permission error) is
        logged and swallowed — discovery is a convenience, not a dependency.
        """
        try:
            from zeroconf import ServiceInfo
            from zeroconf.asyncio import AsyncZeroconf
        except ImportError:
            logger.warning(
                "zeroconf is not installed — mDNS discovery disabled. "
                "The unit can still be set up by entering its IP address directly."
            )
            return

        try:
            port = int(config.get("backend_port", BACKEND_PORT))
            local_ip = _local_ip_address()

            self._service_info = ServiceInfo(
                type_=MDNS_SERVICE_TYPE,
                name=_service_name(),
                addresses=[socket.inet_aton(local_ip)],
                port=port,
                properties={
                    "unit_id": str(config.get("unit_id", "vortex-unset")),
                    "unit_name": str(config.get("unit_name", "River Vortex")),
                    "location": str(config.get("location", "Unknown Room")),
                    "version": VERSION,
                    "configured": "true" if config.get("configured", False) else "false",
                    "setup_path": f"{RIVER_SONG_SETUP_BASE}/info",
                },
            )

            self._aiozc = AsyncZeroconf()
            await self._aiozc.async_register_service(self._service_info)
            logger.info(
                "Advertising on mDNS as %s (%s:%d, configured=%s)",
                self._service_info.name,
                local_ip,
                port,
                config.get("configured", False),
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("mDNS advertisement failed (continuing without it): %s", exc)
            self._aiozc = None
            self._service_info = None

    async def stop(self) -> None:
        """Unregister the mDNS service and close Zeroconf, if active."""
        if not self._aiozc:
            return
        try:
            if self._service_info:
                await self._aiozc.async_unregister_service(self._service_info)
            await self._aiozc.async_close()
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug("Error while stopping mDNS advertisement: %s", exc)
        finally:
            self._aiozc = None
            self._service_info = None
