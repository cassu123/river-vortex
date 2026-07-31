"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        connectivity/api_client.py
Purpose:     HTTP client for all River Song API communication. Handles
             authentication, retries, timeouts, and the voice command audio
             streaming endpoint. All River Song API calls route through here.
             Endpoint base: /api/vortex/v1/
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
from typing import Any, Dict, Optional

import httpx

from core.config import config
from core.constants import (
    API_CONNECT_TIMEOUT,
    API_READ_TIMEOUT,
    API_STREAM_TIMEOUT,
    RIVER_SONG_COMMAND_ENDPOINT,
    RIVER_SONG_HEALTH_ENDPOINT,
    RIVER_SONG_STATUS_ENDPOINT,
    RIVER_SONG_SURFACE_ACTION_ENDPOINT,
)

logger = logging.getLogger(__name__)


class APIClientError(Exception):
    """Raised when a River Song API call fails."""
    pass


class APIClient:
    """
    Async HTTP client for the River Song API.

    All communication with River Song routes through this class.
    Handles:
    - Authentication via API key header
    - Timeouts and retries
    - Voice command audio upload and TTS response download
    - Health checks

    Usage:
        client = APIClient()
        response_audio = await client.send_voice_command(pcm_bytes)
    """

    def __init__(self) -> None:
        """Initialize the API client with configuration from config singleton."""
        self._base_url: str = config.get("river_song_api_url", "http://riversong.local")
        self._api_key: str = config.get("river_song_api_key", "")
        self._unit_id: str = config.get("unit_id", "vortex-unset")

        self._headers: Dict[str, str] = {
            "X-Vortex-Unit-ID": self._unit_id,
            "User-Agent": f"RiverVortex/1.0 unit/{self._unit_id}",
        }
        if self._api_key:
            self._headers["Authorization"] = f"Bearer {self._api_key}"

    # ─────────────────────────────────────────────────────────────────────────
    # Voice Command
    # ─────────────────────────────────────────────────────────────────────────

    async def send_voice_command(self, audio_bytes: bytes) -> Optional[bytes]:
        """
        Send captured voice command audio to River Song for processing.

        The audio is raw PCM (16-bit, mono, 16kHz) captured after wake word
        detection. River Song processes the command and returns TTS audio.

        Args:
            audio_bytes: Raw PCM audio bytes of the voice command.

        Returns:
            TTS response audio bytes (WAV), or None if River Song returns
            no audio (e.g., silent acknowledgement or error).

        Raises:
            APIClientError: On network failure or non-2xx response.
        """
        if not audio_bytes:
            raise APIClientError("Cannot send empty audio to River Song.")

        url = f"{self._base_url}{RIVER_SONG_COMMAND_ENDPOINT}"
        logger.debug("Sending %d bytes of audio to River Song: %s", len(audio_bytes), url)

        try:
            async with httpx.AsyncClient(
                headers=self._headers,
                timeout=httpx.Timeout(
                    connect=API_CONNECT_TIMEOUT,
                    read=API_STREAM_TIMEOUT,
                    write=API_STREAM_TIMEOUT,
                    pool=API_CONNECT_TIMEOUT,
                ),
            ) as client:
                response = await client.post(
                    url,
                    content=audio_bytes,
                    headers={
                        **self._headers,
                        "Content-Type": "audio/pcm",
                        "X-Sample-Rate": "16000",
                        "X-Channels": "1",
                        "X-Bit-Depth": "16",
                    },
                )

            if response.status_code == 204:
                # River Song acknowledged but has no audio response
                logger.debug("River Song returned 204 — no audio response.")
                return None

            if response.status_code != 200:
                raise APIClientError(
                    f"River Song command endpoint returned {response.status_code}: "
                    f"{response.text[:200]}"
                )

            response_audio = response.content
            logger.debug("Received %d bytes of TTS audio from River Song.", len(response_audio))
            return response_audio

        except httpx.TimeoutException as exc:
            raise APIClientError(f"River Song API timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise APIClientError(f"River Song API request failed: {exc}") from exc

    # ─────────────────────────────────────────────────────────────────────────
    # Surfaces
    # ─────────────────────────────────────────────────────────────────────────

    async def send_surface_action(self, surface_id: str, intent: str) -> Dict[str, Any]:
        """
        Report that someone tapped a button on a surface card.

        The unit deliberately does not act on the intent itself. River Song
        pushed the card, River Song knows what the button meant, and River
        Song re-checks whether the action is permitted — a confirm card on a
        wall panel must not become a second, weaker permission system.

        Args:
            surface_id: The id of the card that was tapped.
            intent:     The opaque intent string River Song attached to the
                        button. Vortex never parses it.

        Returns:
            River Song's response body.

        Raises:
            APIClientError: On network failure or non-2xx response. The caller
                            leaves the card on screen when this raises, so a
                            tap that never arrived does not look like it did.
        """
        url = f"{self._base_url}{RIVER_SONG_SURFACE_ACTION_ENDPOINT}"
        payload = {"surface_id": surface_id, "intent": intent, "unit_id": self._unit_id}

        try:
            async with httpx.AsyncClient(
                headers=self._headers,
                timeout=httpx.Timeout(connect=API_CONNECT_TIMEOUT, read=API_READ_TIMEOUT),
            ) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise APIClientError(f"River Song API timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise APIClientError(f"River Song API request failed: {exc}") from exc

        if response.status_code >= 400:
            raise APIClientError(
                f"River Song surface action returned {response.status_code}: "
                f"{response.text[:200]}"
            )
        try:
            return response.json()
        except ValueError:
            # A 2xx with no body is a perfectly good acknowledgement.
            return {"accepted": True}

    # ─────────────────────────────────────────────────────────────────────────
    # Status & Health
    # ─────────────────────────────────────────────────────────────────────────

    async def get_status(self) -> Dict[str, Any]:
        """
        Fetch the River Song system status.

        Returns:
            Status dict from River Song, or an error dict on failure.
        """
        url = f"{self._base_url}{RIVER_SONG_STATUS_ENDPOINT}"
        try:
            async with httpx.AsyncClient(
                headers=self._headers,
                timeout=httpx.Timeout(connect=API_CONNECT_TIMEOUT, read=API_READ_TIMEOUT),
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            logger.warning("Failed to fetch River Song status: %s", exc)
            return {"error": str(exc), "available": False}

    async def health_check(self) -> bool:
        """
        Ping the River Song health endpoint.

        Returns:
            True if River Song is reachable and healthy, False otherwise.
        """
        url = f"{self._base_url}{RIVER_SONG_HEALTH_ENDPOINT}"
        try:
            async with httpx.AsyncClient(
                headers=self._headers,
                timeout=httpx.Timeout(connect=API_CONNECT_TIMEOUT, read=5.0),
            ) as client:
                response = await client.get(url)
                return response.status_code == 200
        except Exception as exc:
            logger.debug("River Song health check failed: %s", exc)
            return False
