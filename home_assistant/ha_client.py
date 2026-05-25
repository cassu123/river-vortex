"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        home_assistant/ha_client.py
Purpose:     Home Assistant WebSocket and REST API client. Manages the
             persistent WebSocket connection to HA, handles authentication,
             subscribes to state change events, and provides a clean async
             interface for device control and state queries.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from core.constants import (
    HA_MAX_RECONNECT_ATTEMPTS,
    HA_PING_INTERVAL_SECONDS,
    HA_RECONNECT_INTERVAL_SECONDS,
    HA_WS_PATH,
    HA_REST_PATH,
    HA_COMMAND_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


class HAConnectionError(Exception):
    """Raised when the Home Assistant connection cannot be established."""
    pass


class HAClient:
    """
    Async Home Assistant client using WebSocket + REST.

    Maintains a persistent WebSocket connection for real-time state updates
    and event subscriptions. Uses the REST API for one-off service calls.

    Usage:
        client = HAClient(url="http://homeassistant.local:8123", token="...")
        await client.connect()
        await client.call_service("light", "turn_on", {"entity_id": "light.kitchen"})
        await client.disconnect()
    """

    def __init__(self, url: str, token: str) -> None:
        """
        Initialize the HA client.

        Args:
            url:   Base URL of the Home Assistant instance (no trailing slash).
            token: Long-lived access token from HA profile settings.
        """
        self._url: str = url.rstrip("/")
        self._token: str = token
        self._ws_url: str = self._url.replace("http", "ws") + HA_WS_PATH
        self._rest_url: str = self._url + HA_REST_PATH

        self._ws = None                         # websockets connection
        self._connected: bool = False
        self._message_id: int = 1
        self._pending: Dict[int, asyncio.Future] = {}
        self._event_listeners: Dict[str, List[Callable]] = {}
        self._reconnect_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._receive_task: Optional[asyncio.Task] = None

    # ─────────────────────────────────────────────────────────────────────────
    # Connection Lifecycle
    # ─────────────────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """
        Establish the WebSocket connection to Home Assistant.

        Performs the HA WebSocket authentication handshake and subscribes
        to state_changed events.

        Raises:
            HAConnectionError: If authentication fails or the server is unreachable.
        """
        await self._connect_ws()
        self._ping_task = asyncio.create_task(self._ping_loop(), name="ha-ping")
        logger.info("Connected to Home Assistant at %s", self._url)

    async def disconnect(self) -> None:
        """Close the WebSocket connection and cancel background tasks."""
        self._connected = False
        for task in (self._ping_task, self._receive_task, self._reconnect_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:  # pylint: disable=broad-except
                pass
        logger.info("Disconnected from Home Assistant.")

    @property
    def is_connected(self) -> bool:
        """Return True if the WebSocket connection is active."""
        return self._connected

    # ─────────────────────────────────────────────────────────────────────────
    # Service Calls
    # ─────────────────────────────────────────────────────────────────────────

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Call a Home Assistant service via WebSocket.

        Args:
            domain:       HA domain (e.g., "light", "switch", "climate").
            service:      Service name (e.g., "turn_on", "set_temperature").
            service_data: Optional dict of service parameters (e.g., entity_id).

        Returns:
            The HA response dict.

        Raises:
            HAConnectionError: If not connected.
            asyncio.TimeoutError: If HA does not respond within the timeout.
        """
        if not self._connected:
            raise HAConnectionError("Not connected to Home Assistant.")

        msg_id = self._next_id()
        message = {
            "id": msg_id,
            "type": "call_service",
            "domain": domain,
            "service": service,
        }
        if service_data:
            message["service_data"] = service_data

        return await self._send_and_wait(msg_id, message)

    async def get_state(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch the current state of a Home Assistant entity via REST.

        Args:
            entity_id: The HA entity ID (e.g., "light.kitchen").

        Returns:
            Entity state dict, or None if the entity is not found.
        """
        try:
            import httpx
            async with httpx.AsyncClient(
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=HA_COMMAND_TIMEOUT_SECONDS,
            ) as client:
                response = await client.get(
                    f"{self._rest_url}/states/{entity_id}"
                )
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            logger.error("Failed to get state for %s: %s", entity_id, exc)
            return None

    async def get_all_states(self) -> List[Dict[str, Any]]:
        """
        Fetch all entity states from Home Assistant via REST.

        Returns:
            List of entity state dicts.
        """
        try:
            import httpx
            async with httpx.AsyncClient(
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=HA_COMMAND_TIMEOUT_SECONDS,
            ) as client:
                response = await client.get(f"{self._rest_url}/states")
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            logger.error("Failed to fetch all HA states: %s", exc)
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # Event Subscriptions
    # ─────────────────────────────────────────────────────────────────────────

    def on_state_changed(self, entity_id: str, callback: Callable[[Dict], None]) -> None:
        """
        Register a callback for state changes on a specific entity.

        Args:
            entity_id: The HA entity to watch.
            callback:  Called with the event data dict when the entity changes.
        """
        if entity_id not in self._event_listeners:
            self._event_listeners[entity_id] = []
        self._event_listeners[entity_id].append(callback)
        logger.debug("Registered state_changed listener for %s.", entity_id)

    # ─────────────────────────────────────────────────────────────────────────
    # Private — WebSocket internals
    # ─────────────────────────────────────────────────────────────────────────

    async def _connect_ws(self) -> None:
        """
        Open the WebSocket connection and complete the HA auth handshake.

        Raises:
            HAConnectionError: On auth failure or connection error.
        """
        try:
            import websockets  # type: ignore
            self._ws = await websockets.connect(self._ws_url)
        except Exception as exc:
            raise HAConnectionError(f"Cannot connect to HA WebSocket: {exc}") from exc

        # HA sends auth_required immediately on connect
        auth_req = json.loads(await self._ws.recv())
        if auth_req.get("type") != "auth_required":
            raise HAConnectionError(f"Unexpected HA handshake message: {auth_req}")

        await self._ws.send(json.dumps({"type": "auth", "access_token": self._token}))
        auth_result = json.loads(await self._ws.recv())

        if auth_result.get("type") == "auth_invalid":
            raise HAConnectionError("Home Assistant authentication failed — check HA_TOKEN.")

        if auth_result.get("type") != "auth_ok":
            raise HAConnectionError(f"Unexpected HA auth response: {auth_result}")

        self._connected = True

        # Subscribe to state_changed events
        sub_id = self._next_id()
        await self._ws.send(json.dumps({
            "id": sub_id,
            "type": "subscribe_events",
            "event_type": "state_changed",
        }))

        # Start the receive loop
        self._receive_task = asyncio.create_task(
            self._receive_loop(), name="ha-receive"
        )

    async def _receive_loop(self) -> None:
        """
        Continuously receive messages from the HA WebSocket.

        Routes responses to pending futures and dispatches events to listeners.
        Triggers reconnection on connection loss.
        """
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Received non-JSON from HA WebSocket.")
                    continue

                msg_type = msg.get("type")

                if msg_type == "result":
                    msg_id = msg.get("id")
                    future = self._pending.pop(msg_id, None)
                    if future and not future.done():
                        if msg.get("success"):
                            future.set_result(msg.get("result", {}))
                        else:
                            future.set_exception(
                                HAConnectionError(f"HA service call failed: {msg.get('error')}")
                            )

                elif msg_type == "event":
                    event = msg.get("event", {})
                    if event.get("event_type") == "state_changed":
                        self._dispatch_state_change(event.get("data", {}))

        except Exception as exc:  # pylint: disable=broad-except
            if self._connected:
                logger.warning("HA WebSocket connection lost: %s — scheduling reconnect.", exc)
                self._connected = False
                self._reconnect_task = asyncio.create_task(
                    self._reconnect_loop(), name="ha-reconnect"
                )

    async def _reconnect_loop(self) -> None:
        """
        Attempt to reconnect to Home Assistant after a connection loss.

        Retries up to HA_MAX_RECONNECT_ATTEMPTS times with exponential backoff.
        """
        for attempt in range(1, HA_MAX_RECONNECT_ATTEMPTS + 1):
            logger.info("HA reconnect attempt %d/%d...", attempt, HA_MAX_RECONNECT_ATTEMPTS)
            await asyncio.sleep(HA_RECONNECT_INTERVAL_SECONDS)
            try:
                await self._connect_ws()
                logger.info("Reconnected to Home Assistant.")
                return
            except HAConnectionError as exc:
                logger.warning("Reconnect attempt %d failed: %s", attempt, exc)

        logger.error("Exhausted HA reconnect attempts. Home Assistant integration offline.")

    async def _ping_loop(self) -> None:
        """Send periodic pings to keep the WebSocket connection alive."""
        while self._connected:
            await asyncio.sleep(HA_PING_INTERVAL_SECONDS)
            if self._connected and self._ws:
                try:
                    ping_id = self._next_id()
                    await self._ws.send(json.dumps({"id": ping_id, "type": "ping"}))
                except Exception as exc:
                    logger.debug("HA ping failed: %s", exc)

    async def _send_and_wait(
        self, msg_id: int, message: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send a WebSocket message and wait for the corresponding result.

        Args:
            msg_id:  The message ID (used to match the response).
            message: The message dict to send.

        Returns:
            The result payload from HA.
        """
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[msg_id] = future

        await self._ws.send(json.dumps(message))

        try:
            return await asyncio.wait_for(future, timeout=HA_COMMAND_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise

    def _dispatch_state_change(self, data: Dict[str, Any]) -> None:
        """
        Dispatch a state_changed event to registered listeners.

        Args:
            data: The event data dict from HA (contains entity_id, new_state, old_state).
        """
        entity_id = data.get("entity_id", "")
        listeners = self._event_listeners.get(entity_id, [])
        for listener in listeners:
            try:
                listener(data)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("HA state listener error for %s: %s", entity_id, exc)

    def _next_id(self) -> int:
        """Return the next monotonically increasing message ID."""
        msg_id = self._message_id
        self._message_id += 1
        return msg_id
