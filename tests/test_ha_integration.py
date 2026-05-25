"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_ha_integration.py
Purpose:     Unit tests for the Home Assistant integration — HAClient,
             DeviceControl, and AutomationTrigger. All WebSocket and HTTP
             calls are mocked so tests run without a live HA instance.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def run_async(coro):
    """Run an async coroutine synchronously in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────────
# HAClient tests
# ─────────────────────────────────────────────────────────────────────────────

class TestHAClient(unittest.TestCase):
    """Tests for home_assistant/ha_client.py — HAClient."""

    def _make_client(self):
        from home_assistant.ha_client import HAClient
        return HAClient(url="http://homeassistant.local:8123", token="test-token")

    def test_initial_state_not_connected(self):
        """A new HAClient should not be connected."""
        client = self._make_client()
        self.assertFalse(client.is_connected)

    def test_call_service_raises_when_not_connected(self):
        """call_service() must raise HAConnectionError when not connected."""
        from home_assistant.ha_client import HAConnectionError
        client = self._make_client()
        with self.assertRaises(HAConnectionError):
            run_async(client.call_service("light", "turn_on", {"entity_id": "light.test"}))

    def test_ws_url_built_correctly(self):
        """WebSocket URL should replace http with ws and append the WS path."""
        from home_assistant.ha_client import HAClient
        from core.constants import HA_WS_PATH
        client = HAClient(url="http://homeassistant.local:8123", token="tok")
        self.assertEqual(client._ws_url, f"ws://homeassistant.local:8123{HA_WS_PATH}")

    def test_ws_url_https_to_wss(self):
        """HTTPS URL should produce a WSS WebSocket URL."""
        from home_assistant.ha_client import HAClient
        from core.constants import HA_WS_PATH
        client = HAClient(url="https://homeassistant.example.com", token="tok")
        self.assertEqual(client._ws_url, f"wss://homeassistant.example.com{HA_WS_PATH}")

    def test_next_id_increments(self):
        """_next_id() should return monotonically increasing integers."""
        client = self._make_client()
        ids = [client._next_id() for _ in range(5)]
        self.assertEqual(ids, list(range(1, 6)))

    def test_on_state_changed_registers_listener(self):
        """on_state_changed() should register a callback for the entity."""
        client = self._make_client()
        callback = MagicMock()
        client.on_state_changed("light.kitchen", callback)
        self.assertIn("light.kitchen", client._event_listeners)
        self.assertIn(callback, client._event_listeners["light.kitchen"])

    def test_dispatch_state_change_calls_listener(self):
        """_dispatch_state_change() should call registered listeners."""
        client = self._make_client()
        callback = MagicMock()
        client.on_state_changed("light.kitchen", callback)

        event_data = {
            "entity_id": "light.kitchen",
            "new_state": {"state": "on"},
            "old_state": {"state": "off"},
        }
        client._dispatch_state_change(event_data)
        callback.assert_called_once_with(event_data)

    def test_dispatch_state_change_ignores_unknown_entity(self):
        """_dispatch_state_change() should not raise for unregistered entities."""
        client = self._make_client()
        try:
            client._dispatch_state_change({"entity_id": "light.unknown"})
        except Exception as exc:
            self.fail(f"Raised unexpectedly: {exc}")

    @patch("httpx.AsyncClient")
    def test_get_state_returns_none_on_404(self, mock_client_cls):
        """get_state() should return None when HA returns 404."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        client = self._make_client()
        result = run_async(client.get_state("light.nonexistent"))
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# DeviceControl tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDeviceControl(unittest.TestCase):
    """Tests for home_assistant/device_control.py — DeviceControl."""

    def _make_dc(self, call_service_result=None):
        """Create a DeviceControl with a mocked HAClient."""
        from home_assistant.device_control import DeviceControl
        mock_ha = MagicMock()
        mock_ha.call_service = AsyncMock(return_value=call_service_result or {})
        mock_ha.get_all_states = AsyncMock(return_value=[])
        return DeviceControl(mock_ha), mock_ha

    def test_turn_on_calls_correct_service(self):
        """turn_on() should call the correct HA domain and service."""
        dc, mock_ha = self._make_dc()
        result = run_async(dc.turn_on("light.kitchen"))
        self.assertTrue(result)
        mock_ha.call_service.assert_called_once_with(
            "light", "turn_on", {"entity_id": "light.kitchen"}
        )

    def test_turn_off_calls_correct_service(self):
        """turn_off() should call turn_off on the correct domain."""
        dc, mock_ha = self._make_dc()
        run_async(dc.turn_off("switch.fan"))
        mock_ha.call_service.assert_called_once_with(
            "switch", "turn_off", {"entity_id": "switch.fan"}
        )

    def test_lock_calls_lock_service(self):
        """lock() should call the lock domain lock service."""
        dc, mock_ha = self._make_dc()
        run_async(dc.lock("lock.front_door"))
        mock_ha.call_service.assert_called_once_with(
            "lock", "lock", {"entity_id": "lock.front_door"}
        )

    def test_unlock_calls_unlock_service(self):
        """unlock() should call the lock domain unlock service."""
        dc, mock_ha = self._make_dc()
        run_async(dc.unlock("lock.front_door"))
        mock_ha.call_service.assert_called_once_with(
            "lock", "unlock", {"entity_id": "lock.front_door"}
        )

    def test_set_brightness_converts_percent_to_255(self):
        """set_brightness() should convert percentage to 0-255 range."""
        dc, mock_ha = self._make_dc()
        run_async(dc.set_brightness("light.living_room", 50))
        call_args = mock_ha.call_service.call_args
        service_data = call_args[0][2]
        self.assertEqual(service_data["brightness"], 127)  # 50% of 255

    def test_set_temperature_passes_value(self):
        """set_temperature() should pass the temperature value to HA."""
        dc, mock_ha = self._make_dc()
        run_async(dc.set_temperature("climate.thermostat", 72.0))
        call_args = mock_ha.call_service.call_args
        service_data = call_args[0][2]
        self.assertEqual(service_data["temperature"], 72.0)

    def test_returns_false_on_ha_connection_error(self):
        """Service calls should return False when HA is not connected."""
        from home_assistant.ha_client import HAConnectionError
        from home_assistant.device_control import DeviceControl
        mock_ha = MagicMock()
        mock_ha.call_service = AsyncMock(side_effect=HAConnectionError("Not connected"))
        dc = DeviceControl(mock_ha)
        result = run_async(dc.turn_on("light.test"))
        self.assertFalse(result)

    def test_domain_for_extracts_domain(self):
        """_domain_for() should extract the domain from an entity_id."""
        from home_assistant.device_control import DeviceControl
        self.assertEqual(DeviceControl._domain_for("light.kitchen"), "light")
        self.assertEqual(DeviceControl._domain_for("climate.thermostat"), "climate")
        self.assertEqual(DeviceControl._domain_for("lock.front_door"), "lock")


# ─────────────────────────────────────────────────────────────────────────────
# AutomationTrigger tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAutomationTrigger(unittest.TestCase):
    """Tests for home_assistant/automation_trigger.py — AutomationTrigger."""

    def _make_trigger(self):
        from home_assistant.automation_trigger import AutomationTrigger
        mock_ha = MagicMock()
        mock_ha.call_service = AsyncMock(return_value={})
        return AutomationTrigger(mock_ha), mock_ha

    def test_fire_automation_calls_trigger_service(self):
        """fire_automation() should call automation.trigger."""
        trigger, mock_ha = self._make_trigger()
        result = run_async(trigger.fire_automation("automation.goodnight"))
        self.assertTrue(result)
        mock_ha.call_service.assert_called_once_with(
            "automation", "trigger", {"entity_id": "automation.goodnight"}
        )

    def test_run_script_calls_script_turn_on(self):
        """run_script() should call script.turn_on."""
        trigger, mock_ha = self._make_trigger()
        result = run_async(trigger.run_script("script.movie_mode"))
        self.assertTrue(result)
        mock_ha.call_service.assert_called_once_with(
            "script", "turn_on", {"entity_id": "script.movie_mode"}
        )

    def test_activate_scene_calls_scene_turn_on(self):
        """activate_scene() should call scene.turn_on."""
        trigger, mock_ha = self._make_trigger()
        result = run_async(trigger.activate_scene("scene.evening"))
        self.assertTrue(result)
        mock_ha.call_service.assert_called_once_with(
            "scene", "turn_on", {"entity_id": "scene.evening"}
        )

    def test_returns_false_on_connection_error(self):
        """All methods should return False when HA is not connected."""
        from home_assistant.ha_client import HAConnectionError
        from home_assistant.automation_trigger import AutomationTrigger
        mock_ha = MagicMock()
        mock_ha.call_service = AsyncMock(side_effect=HAConnectionError("Not connected"))
        trigger = AutomationTrigger(mock_ha)

        self.assertFalse(run_async(trigger.fire_automation("automation.test")))
        self.assertFalse(run_async(trigger.run_script("script.test")))
        self.assertFalse(run_async(trigger.activate_scene("scene.test")))


if __name__ == "__main__":
    unittest.main()
