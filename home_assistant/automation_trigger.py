"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        home_assistant/automation_trigger.py
Purpose:     Trigger Home Assistant automations and scripts from River Vortex
             events. Provides a clean interface for firing HA automations,
             running scripts, and activating scenes in response to voice
             commands, presence detection, or intercom events.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import logging
from typing import Any, Dict, Optional

from core.constants import HADomain, HAService
from home_assistant.ha_client import HAClient, HAConnectionError

logger = logging.getLogger(__name__)


class AutomationTrigger:
    """
    Triggers Home Assistant automations, scripts, and scenes.

    Used by River Song command handlers to execute complex HA sequences
    in response to voice commands (e.g., "goodnight routine", "movie mode").

    Usage:
        trigger = AutomationTrigger(ha_client)
        await trigger.fire_automation("automation.goodnight")
        await trigger.run_script("script.movie_mode")
        await trigger.activate_scene("scene.evening")
    """

    def __init__(self, ha_client: HAClient) -> None:
        """
        Initialize AutomationTrigger.

        Args:
            ha_client: Connected HAClient instance.
        """
        self._ha = ha_client

    async def fire_automation(self, automation_id: str) -> bool:
        """
        Trigger a Home Assistant automation.

        Args:
            automation_id: The HA automation entity ID (e.g., "automation.goodnight").

        Returns:
            True on success, False on failure.
        """
        try:
            await self._ha.call_service(
                HADomain.AUTOMATION,
                HAService.TRIGGER,
                {"entity_id": automation_id},
            )
            logger.info("Triggered automation: %s", automation_id)
            return True
        except HAConnectionError as exc:
            logger.error("Cannot trigger automation %s — HA not connected: %s", automation_id, exc)
            return False
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to trigger automation %s: %s", automation_id, exc)
            return False

    async def run_script(
        self,
        script_id: str,
        variables: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Run a Home Assistant script.

        Args:
            script_id:  The HA script entity ID (e.g., "script.movie_mode").
            variables:  Optional dict of script variables to pass.

        Returns:
            True on success, False on failure.
        """
        service_data: Dict[str, Any] = {"entity_id": script_id}
        if variables:
            service_data["variables"] = variables

        try:
            await self._ha.call_service(HADomain.SCRIPT, HAService.TURN_ON, service_data)
            logger.info("Ran script: %s", script_id)
            return True
        except HAConnectionError as exc:
            logger.error("Cannot run script %s — HA not connected: %s", script_id, exc)
            return False
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to run script %s: %s", script_id, exc)
            return False

    async def activate_scene(self, scene_id: str) -> bool:
        """
        Activate a Home Assistant scene.

        Args:
            scene_id: The HA scene entity ID (e.g., "scene.evening").

        Returns:
            True on success, False on failure.
        """
        try:
            await self._ha.call_service(
                HADomain.SCENE,
                HAService.TURN_ON,
                {"entity_id": scene_id},
            )
            logger.info("Activated scene: %s", scene_id)
            return True
        except HAConnectionError as exc:
            logger.error("Cannot activate scene %s — HA not connected: %s", scene_id, exc)
            return False
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to activate scene %s: %s", scene_id, exc)
            return False

    async def set_input_boolean(self, entity_id: str, state: bool) -> bool:
        """
        Set a Home Assistant input_boolean helper.

        Useful for toggling virtual switches that drive automations.

        Args:
            entity_id: The input_boolean entity ID.
            state:     True to turn on, False to turn off.

        Returns:
            True on success, False on failure.
        """
        service = HAService.TURN_ON if state else HAService.TURN_OFF
        try:
            await self._ha.call_service(
                HADomain.INPUT_BOOLEAN,
                service,
                {"entity_id": entity_id},
            )
            logger.info("Set input_boolean %s → %s", entity_id, "on" if state else "off")
            return True
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to set input_boolean %s: %s", entity_id, exc)
            return False
