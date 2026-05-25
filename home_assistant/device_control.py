"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        home_assistant/device_control.py
Purpose:     High-level device control interface built on top of HAClient.
             Provides typed, intent-based methods for controlling lights,
             switches, climate, locks, covers, and media players via
             Home Assistant. Called by River Song command handlers and the
             frontend API.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
from typing import Any, Dict, List, Optional

from core.constants import HADomain, HAService
from home_assistant.ha_client import HAClient, HAConnectionError

logger = logging.getLogger(__name__)


class DeviceControl:
    """
    High-level device control interface for Home Assistant entities.

    Wraps HAClient.call_service() with typed, intent-based methods.
    All methods are async and safe to call even when HA is disconnected
    (they log a warning and return False rather than raising).

    Usage:
        dc = DeviceControl(ha_client)
        await dc.turn_on("light.kitchen")
        await dc.set_brightness("light.living_room", 75)
        await dc.set_temperature("climate.thermostat", 72)
    """

    def __init__(self, ha_client: HAClient) -> None:
        """
        Initialize DeviceControl.

        Args:
            ha_client: Connected HAClient instance.
        """
        self._ha = ha_client

    # ─────────────────────────────────────────────────────────────────────────
    # Generic On/Off/Toggle
    # ─────────────────────────────────────────────────────────────────────────

    async def turn_on(self, entity_id: str, **kwargs: Any) -> bool:
        """
        Turn on any HA entity that supports the turn_on service.

        Args:
            entity_id: The HA entity ID.
            **kwargs:  Additional service data (e.g., brightness, color_temp).

        Returns:
            True on success, False on failure.
        """
        return await self._call(
            self._domain_for(entity_id),
            HAService.TURN_ON,
            {"entity_id": entity_id, **kwargs},
        )

    async def turn_off(self, entity_id: str) -> bool:
        """
        Turn off any HA entity that supports the turn_off service.

        Args:
            entity_id: The HA entity ID.

        Returns:
            True on success, False on failure.
        """
        return await self._call(
            self._domain_for(entity_id),
            HAService.TURN_OFF,
            {"entity_id": entity_id},
        )

    async def toggle(self, entity_id: str) -> bool:
        """
        Toggle any HA entity that supports the toggle service.

        Args:
            entity_id: The HA entity ID.

        Returns:
            True on success, False on failure.
        """
        return await self._call(
            self._domain_for(entity_id),
            HAService.TOGGLE,
            {"entity_id": entity_id},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Lights
    # ─────────────────────────────────────────────────────────────────────────

    async def set_brightness(self, entity_id: str, brightness_pct: int) -> bool:
        """
        Set light brightness.

        Args:
            entity_id:      Light entity ID.
            brightness_pct: Brightness percentage (0–100).

        Returns:
            True on success.
        """
        brightness_255 = int(max(0, min(100, brightness_pct)) * 2.55)
        return await self._call(
            HADomain.LIGHT,
            HAService.TURN_ON,
            {"entity_id": entity_id, "brightness": brightness_255},
        )

    async def set_color_temp(self, entity_id: str, kelvin: int) -> bool:
        """
        Set light color temperature.

        Args:
            entity_id: Light entity ID.
            kelvin:    Color temperature in Kelvin (2700–6500 typical).

        Returns:
            True on success.
        """
        return await self._call(
            HADomain.LIGHT,
            HAService.TURN_ON,
            {"entity_id": entity_id, "kelvin": kelvin},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Climate
    # ─────────────────────────────────────────────────────────────────────────

    async def set_temperature(self, entity_id: str, temperature: float) -> bool:
        """
        Set thermostat target temperature.

        Args:
            entity_id:   Climate entity ID.
            temperature: Target temperature (unit matches HA configuration).

        Returns:
            True on success.
        """
        return await self._call(
            HADomain.CLIMATE,
            HAService.SET_TEMPERATURE,
            {"entity_id": entity_id, "temperature": temperature},
        )

    async def set_hvac_mode(self, entity_id: str, mode: str) -> bool:
        """
        Set HVAC mode (heat, cool, auto, off).

        Args:
            entity_id: Climate entity ID.
            mode:      HVAC mode string.

        Returns:
            True on success.
        """
        return await self._call(
            HADomain.CLIMATE,
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": mode},
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Locks
    # ─────────────────────────────────────────────────────────────────────────

    async def lock(self, entity_id: str) -> bool:
        """
        Lock a lock entity.

        Args:
            entity_id: Lock entity ID.

        Returns:
            True on success.
        """
        return await self._call(HADomain.LOCK, HAService.LOCK, {"entity_id": entity_id})

    async def unlock(self, entity_id: str) -> bool:
        """
        Unlock a lock entity.

        Args:
            entity_id: Lock entity ID.

        Returns:
            True on success.
        """
        return await self._call(HADomain.LOCK, HAService.UNLOCK, {"entity_id": entity_id})

    # ─────────────────────────────────────────────────────────────────────────
    # Covers (blinds, garage doors)
    # ─────────────────────────────────────────────────────────────────────────

    async def open_cover(self, entity_id: str) -> bool:
        """Open a cover (blind, garage door, etc.)."""
        return await self._call(HADomain.COVER, HAService.OPEN_COVER, {"entity_id": entity_id})

    async def close_cover(self, entity_id: str) -> bool:
        """Close a cover."""
        return await self._call(HADomain.COVER, HAService.CLOSE_COVER, {"entity_id": entity_id})

    # ─────────────────────────────────────────────────────────────────────────
    # State Queries
    # ─────────────────────────────────────────────────────────────────────────

    async def get_state(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the current state of an entity.

        Args:
            entity_id: The HA entity ID.

        Returns:
            Entity state dict, or None if unavailable.
        """
        return await self._ha.get_state(entity_id)

    async def get_all_lights(self) -> List[Dict[str, Any]]:
        """
        Return all light entities and their current states.

        Returns:
            List of entity state dicts for all light.* entities.
        """
        all_states = await self._ha.get_all_states()
        return [s for s in all_states if s.get("entity_id", "").startswith("light.")]

    async def get_all_switches(self) -> List[Dict[str, Any]]:
        """Return all switch entities and their current states."""
        all_states = await self._ha.get_all_states()
        return [s for s in all_states if s.get("entity_id", "").startswith("switch.")]

    # ─────────────────────────────────────────────────────────────────────────
    # Private
    # ─────────────────────────────────────────────────────────────────────────

    async def _call(
        self,
        domain: str,
        service: str,
        service_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Execute a Home Assistant service call with error handling.

        Args:
            domain:       HA domain string.
            service:      HA service string.
            service_data: Optional service parameters.

        Returns:
            True on success, False on any error.
        """
        try:
            await self._ha.call_service(domain, service, service_data)
            logger.debug("HA service call: %s.%s %s", domain, service, service_data)
            return True
        except HAConnectionError as exc:
            logger.error("HA not connected — cannot call %s.%s: %s", domain, service, exc)
            return False
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("HA service call %s.%s failed: %s", domain, service, exc)
            return False

    @staticmethod
    def _domain_for(entity_id: str) -> str:
        """
        Extract the HA domain from an entity ID.

        Args:
            entity_id: Full entity ID (e.g., "light.kitchen").

        Returns:
            Domain string (e.g., "light").
        """
        return entity_id.split(".")[0] if "." in entity_id else "homeassistant"
