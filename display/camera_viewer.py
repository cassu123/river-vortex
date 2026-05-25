"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        display/camera_viewer.py
Purpose:     Camera feed management for the display. Fetches camera stream
             URLs from Home Assistant, provides snapshot and stream endpoints
             to the React frontend, and manages camera access permissions
             through the privacy manager.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
from typing import Any, Dict, List, Optional

from core.config import config

logger = logging.getLogger(__name__)


class CameraViewer:
    """
    Manages camera feed access for the River Vortex display.

    Fetches camera entity states from Home Assistant and provides
    stream/snapshot URLs to the React frontend. Camera access is
    gated by the privacy manager.

    All camera streams are proxied through the local backend — no
    camera credentials are exposed to the frontend directly.
    """

    def __init__(self, ha_client=None, privacy_manager=None) -> None:
        """
        Initialize CameraViewer.

        Args:
            ha_client:       HAClient instance for fetching camera states.
            privacy_manager: PrivacyManager for access control checks.
        """
        self._ha = ha_client
        self._privacy = privacy_manager
        self._camera_cache: Dict[str, Dict[str, Any]] = {}

    async def get_cameras(self) -> List[Dict[str, Any]]:
        """
        Fetch all available camera entities from Home Assistant.

        Returns:
            List of camera info dicts with entity_id, name, and stream_url.
        """
        if not self._ha or not self._ha.is_connected:
            logger.warning("HA not connected — cannot fetch cameras.")
            return []

        try:
            all_states = await self._ha.get_all_states()
            cameras = []
            for state in all_states:
                entity_id = state.get("entity_id", "")
                if entity_id.startswith("camera."):
                    cameras.append({
                        "entity_id": entity_id,
                        "name": state.get("attributes", {}).get("friendly_name", entity_id),
                        "state": state.get("state", "unknown"),
                        "snapshot_url": self._snapshot_url(entity_id),
                        "stream_url": self._stream_url(entity_id),
                    })
            self._camera_cache = {c["entity_id"]: c for c in cameras}
            return cameras
        except Exception as exc:
            logger.error("Failed to fetch cameras from HA: %s", exc)
            return []

    async def get_snapshot(self, entity_id: str) -> Optional[bytes]:
        """
        Fetch a JPEG snapshot from a camera entity via HA REST API.

        Args:
            entity_id: The camera entity ID.

        Returns:
            JPEG image bytes, or None on failure.
        """
        if not self._ha:
            return None

        ha_url = config.get("ha_url", "http://homeassistant.local:8123")
        ha_token = config.get("ha_token", "")
        snapshot_url = f"{ha_url}/api/camera_proxy/{entity_id}"

        try:
            import httpx
            async with httpx.AsyncClient(
                headers={"Authorization": f"Bearer {ha_token}"},
                timeout=10.0,
            ) as client:
                response = await client.get(snapshot_url)
                if response.status_code == 200:
                    return response.content
                logger.warning(
                    "Camera snapshot for %s returned %d.", entity_id, response.status_code
                )
                return None
        except Exception as exc:
            logger.error("Failed to fetch snapshot for %s: %s", entity_id, exc)
            return None

    def _snapshot_url(self, entity_id: str) -> str:
        """
        Build the local proxy URL for a camera snapshot.

        Args:
            entity_id: Camera entity ID.

        Returns:
            Local API URL for the snapshot proxy endpoint.
        """
        return f"/api/cameras/{entity_id}/snapshot"

    def _stream_url(self, entity_id: str) -> str:
        """
        Build the local proxy URL for a camera stream.

        Args:
            entity_id: Camera entity ID.

        Returns:
            Local API URL for the stream proxy endpoint.
        """
        return f"/api/cameras/{entity_id}/stream"
