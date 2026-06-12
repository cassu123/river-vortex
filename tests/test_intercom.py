"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_intercom.py
Purpose:     Unit tests for room-to-room "Drop In" intercom calls —
             IntercomManager (intercom/intercom_manager.py) and the
             /api/vortex/v1/intercom REST API (core/intercom_api.py),
             including call signaling (call/answer/decline/end), incoming
             call-request handling, ring/call timeouts, and audio framing.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-12
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def run_async(coro):
    """Run an async coroutine synchronously in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


PEER = {
    "unit_id": "vortex-bedroom-01",
    "unit_name": "Bedroom Vortex",
    "location": "Bedroom",
    "ip": "192.168.1.50",
    "intercom_port": 5005,
    "last_seen": 12345.0,
}


def _control_payload(msg_type: str, unit_id: str = "vortex-bedroom-01",
                      unit_name: str = "Bedroom Vortex", location: str = "Bedroom") -> bytes:
    return json.dumps({
        "type": msg_type,
        "unit_id": unit_id,
        "unit_name": unit_name,
        "location": location,
    }).encode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# IntercomManager — call control
# ─────────────────────────────────────────────────────────────────────────────

class TestIntercomManagerCallControl(unittest.TestCase):
    """Tests for intercom/intercom_manager.py — call(), answer(), decline(), end_call()."""

    def setUp(self):
        patcher = patch("core.ws_hub.ws_hub.broadcast", new_callable=AsyncMock)
        self.mock_broadcast = patcher.start()
        self.addCleanup(patcher.stop)

    def _make_manager(self, microphone=None, speaker=None):
        from intercom.intercom_manager import IntercomManager
        manager = IntercomManager(microphone=microphone, speaker=speaker)
        self.addCleanup(lambda: run_async(manager._reset_to_idle()))
        return manager

    def test_initial_state_is_idle(self):
        manager = self._make_manager()
        self.assertEqual(manager.state, "idle")
        self.assertEqual(manager.get_state(), {"state": "idle", "peer": None})

    def test_call_success_sets_calling_state(self):
        manager = self._make_manager()
        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
            state = run_async(manager.call("vortex-bedroom-01"))
        self.assertEqual(state["state"], "calling")
        self.assertEqual(state["peer"], {
            "unit_id": "vortex-bedroom-01",
            "unit_name": "Bedroom Vortex",
            "location": "Bedroom",
        })
        self.assertEqual(manager.state, "calling")

    def test_call_unknown_peer_raises(self):
        from intercom.intercom_manager import IntercomError
        manager = self._make_manager()
        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=None):
            with self.assertRaises(IntercomError):
                run_async(manager.call("vortex-unknown"))
        self.assertEqual(manager.state, "idle")

    def test_call_while_not_idle_raises(self):
        from intercom.intercom_manager import IntercomError
        manager = self._make_manager()
        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
            run_async(manager.call("vortex-bedroom-01"))
            with self.assertRaises(IntercomError):
                run_async(manager.call("vortex-bedroom-01"))

    def test_answer_without_incoming_call_raises(self):
        from intercom.intercom_manager import IntercomError
        manager = self._make_manager()
        with self.assertRaises(IntercomError):
            run_async(manager.answer())

    def test_decline_without_incoming_call_raises(self):
        from intercom.intercom_manager import IntercomError
        manager = self._make_manager()
        with self.assertRaises(IntercomError):
            run_async(manager.decline())

    def test_end_call_when_idle_is_noop(self):
        manager = self._make_manager()
        state = run_async(manager.end_call())
        self.assertEqual(state, {"state": "idle", "peer": None})

    def test_end_call_during_active_call_resets_to_idle(self):
        manager = self._make_manager()
        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
            run_async(manager.call("vortex-bedroom-01"))
        run_async(manager._activate_call())
        self.assertEqual(manager.state, "active")

        state = run_async(manager.end_call())
        self.assertEqual(state, {"state": "idle", "peer": None})
        self.assertEqual(manager.state, "idle")

    def test_broadcast_on_call_state_changes(self):
        manager = self._make_manager()
        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
            state = run_async(manager.call("vortex-bedroom-01"))
        self.mock_broadcast.assert_any_call({"type": "intercom_update", "intercom": state})

    # ── Callbacks ────────────────────────────────────────────────────────────

    def test_on_call_ended_callback_invoked_on_hangup(self):
        manager = self._make_manager()
        callback = MagicMock()
        manager.on_call_ended(callback)

        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
            run_async(manager.call("vortex-bedroom-01"))
        run_async(manager.end_call())

        callback.assert_called_once()

    def test_on_call_ended_not_invoked_when_already_idle(self):
        manager = self._make_manager()
        callback = MagicMock()
        manager.on_call_ended(callback)
        run_async(manager.end_call())
        callback.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# IntercomManager — incoming control messages
# ─────────────────────────────────────────────────────────────────────────────

class TestIntercomManagerControlMessages(unittest.TestCase):
    """Tests for intercom/intercom_manager.py — _handle_control_message()."""

    def setUp(self):
        patcher = patch("core.ws_hub.ws_hub.broadcast", new_callable=AsyncMock)
        self.mock_broadcast = patcher.start()
        self.addCleanup(patcher.stop)

    def _make_manager(self, microphone=None, speaker=None):
        from intercom.intercom_manager import IntercomManager
        manager = IntercomManager(microphone=microphone, speaker=speaker)
        self.addCleanup(lambda: run_async(manager._reset_to_idle()))
        return manager

    def _dispatch(self, manager, payload, sender_ip="192.168.1.50"):
        async def _run():
            manager._handle_control_message(payload, sender_ip)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        run_async(_run())

    def test_call_request_while_idle_sets_ringing(self):
        manager = self._make_manager()
        self._dispatch(manager, _control_payload("call_request"))

        state = manager.get_state()
        self.assertEqual(state["state"], "ringing")
        self.assertEqual(state["peer"], {
            "unit_id": "vortex-bedroom-01",
            "unit_name": "Bedroom Vortex",
            "location": "Bedroom",
        })

    def test_call_request_while_busy_sends_call_busy(self):
        manager = self._make_manager()
        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
            run_async(manager.call("vortex-bedroom-01"))  # now CALLING

        manager._send_control = AsyncMock()
        self._dispatch(manager, _control_payload("call_request", unit_id="vortex-office-01",
                                                   unit_name="Office Vortex", location="Office"),
                       sender_ip="192.168.1.60")

        manager._send_control.assert_called_once_with("call_busy", "192.168.1.60")
        self.assertEqual(manager.state, "calling")

    def test_call_accept_activates_call(self):
        manager = self._make_manager()
        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
            run_async(manager.call("vortex-bedroom-01"))

        self._dispatch(manager, _control_payload("call_accept"))
        self.assertEqual(manager.state, "active")

    def test_call_accept_from_unexpected_peer_is_ignored(self):
        manager = self._make_manager()
        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
            run_async(manager.call("vortex-bedroom-01"))

        self._dispatch(manager, _control_payload("call_accept", unit_id="vortex-office-01"))
        self.assertEqual(manager.state, "calling")

    def test_call_decline_resets_to_idle(self):
        manager = self._make_manager()
        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
            run_async(manager.call("vortex-bedroom-01"))

        self._dispatch(manager, _control_payload("call_decline"))
        self.assertEqual(manager.state, "idle")
        self.assertEqual(manager.get_state()["peer"], None)

    def test_call_busy_resets_to_idle(self):
        manager = self._make_manager()
        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
            run_async(manager.call("vortex-bedroom-01"))

        self._dispatch(manager, _control_payload("call_busy"))
        self.assertEqual(manager.state, "idle")

    def test_call_end_resets_active_call(self):
        manager = self._make_manager()
        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
            run_async(manager.call("vortex-bedroom-01"))
        run_async(manager._activate_call())

        self._dispatch(manager, _control_payload("call_end"))
        self.assertEqual(manager.state, "idle")

    def test_call_end_ignored_when_idle(self):
        manager = self._make_manager()
        self._dispatch(manager, _control_payload("call_end"))
        self.assertEqual(manager.state, "idle")

    def test_unknown_message_type_is_ignored(self):
        manager = self._make_manager()
        try:
            self._dispatch(manager, _control_payload("nonsense"))
        except Exception as exc:
            self.fail(f"_handle_control_message raised unexpectedly: {exc}")
        self.assertEqual(manager.state, "idle")

    def test_malformed_payload_is_ignored(self):
        manager = self._make_manager()
        try:
            self._dispatch(manager, b"not json")
        except Exception as exc:
            self.fail(f"_handle_control_message raised unexpectedly: {exc}")
        self.assertEqual(manager.state, "idle")

    # ── on_incoming_call callback ───────────────────────────────────────────

    def test_on_incoming_call_callback_invoked(self):
        manager = self._make_manager()
        callback = MagicMock()
        manager.on_incoming_call(callback)

        self._dispatch(manager, _control_payload("call_request"))
        callback.assert_called_once_with("vortex-bedroom-01")

    def test_on_incoming_call_callback_failure_is_handled(self):
        manager = self._make_manager()
        manager.on_incoming_call(MagicMock(side_effect=RuntimeError("display offline")))
        try:
            self._dispatch(manager, _control_payload("call_request"))
        except Exception as exc:
            self.fail(f"_handle_control_message raised unexpectedly: {exc}")
        self.assertEqual(manager.state, "ringing")


# ─────────────────────────────────────────────────────────────────────────────
# IntercomManager — timeouts
# ─────────────────────────────────────────────────────────────────────────────

class TestIntercomManagerTimeouts(unittest.TestCase):
    """Tests for ring/call timeout handling."""

    def setUp(self):
        patcher = patch("core.ws_hub.ws_hub.broadcast", new_callable=AsyncMock)
        self.mock_broadcast = patcher.start()
        self.addCleanup(patcher.stop)

    def _make_manager(self):
        from intercom.intercom_manager import IntercomManager
        manager = IntercomManager()
        self.addCleanup(lambda: run_async(manager._reset_to_idle()))
        return manager

    def test_ring_timeout_while_calling_resets_to_idle(self):
        manager = self._make_manager()
        with patch("intercom.intercom_manager.INTERCOM_RING_TIMEOUT_SECONDS", 0.01):
            with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
                run_async(manager.call("vortex-bedroom-01"))
            run_async(asyncio.sleep(0.05))
        self.assertEqual(manager.state, "idle")

    def test_ring_timeout_while_ringing_resets_to_idle(self):
        manager = self._make_manager()
        with patch("intercom.intercom_manager.INTERCOM_RING_TIMEOUT_SECONDS", 0.01):

            async def _run():
                manager._handle_control_message(_control_payload("call_request"), "192.168.1.50")
                await asyncio.sleep(0.05)

            run_async(_run())
        self.assertEqual(manager.state, "idle")

    def test_call_timeout_ends_active_call(self):
        manager = self._make_manager()
        with patch("intercom.intercom_manager.INTERCOM_MAX_CALL_DURATION_SECONDS", 0.01):
            with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
                run_async(manager.call("vortex-bedroom-01"))
            run_async(manager._activate_call())
            run_async(asyncio.sleep(0.05))
        self.assertEqual(manager.state, "idle")


# ─────────────────────────────────────────────────────────────────────────────
# IntercomManager — audio framing
# ─────────────────────────────────────────────────────────────────────────────

class TestIntercomManagerAudio(unittest.TestCase):
    """Tests for audio frame handling (_handle_audio_frame, _audio_send_loop, _handle_packet)."""

    def setUp(self):
        patcher = patch("core.ws_hub.ws_hub.broadcast", new_callable=AsyncMock)
        self.mock_broadcast = patcher.start()
        self.addCleanup(patcher.stop)

    def _make_manager(self, microphone=None, speaker=None):
        from intercom.intercom_manager import IntercomManager
        manager = IntercomManager(microphone=microphone, speaker=speaker)
        self.addCleanup(lambda: run_async(manager._reset_to_idle()))
        return manager

    def test_handle_packet_dispatches_control_and_audio(self):
        manager = self._make_manager()
        manager._handle_control_message = MagicMock()
        manager._handle_audio_frame = MagicMock()

        manager._handle_packet(b"\x01" + b"payload", "1.2.3.4")
        manager._handle_control_message.assert_called_once_with(b"payload", "1.2.3.4")

        manager._handle_packet(b"\x02" + b"audio", "1.2.3.4")
        manager._handle_audio_frame.assert_called_once_with(b"audio", "1.2.3.4")

    def test_handle_packet_ignores_empty_data(self):
        manager = self._make_manager()
        manager._handle_control_message = MagicMock()
        manager._handle_audio_frame = MagicMock()
        manager._handle_packet(b"", "1.2.3.4")
        manager._handle_control_message.assert_not_called()
        manager._handle_audio_frame.assert_not_called()

    def test_handle_audio_frame_plays_when_active_and_matching_peer(self):
        from intercom.intercom_manager import IntercomState
        speaker = MagicMock()
        manager = self._make_manager(speaker=speaker)
        manager._state = IntercomState.ACTIVE
        manager._active_peer_ip = "192.168.1.50"

        manager._handle_audio_frame(b"\x00\x01", "192.168.1.50")
        speaker.play_raw.assert_called_once_with(b"\x00\x01")

    def test_handle_audio_frame_ignored_when_not_active(self):
        speaker = MagicMock()
        manager = self._make_manager(speaker=speaker)
        manager._handle_audio_frame(b"\x00\x01", "192.168.1.50")
        speaker.play_raw.assert_not_called()

    def test_handle_audio_frame_ignored_from_wrong_sender(self):
        from intercom.intercom_manager import IntercomState
        speaker = MagicMock()
        manager = self._make_manager(speaker=speaker)
        manager._state = IntercomState.ACTIVE
        manager._active_peer_ip = "192.168.1.50"

        manager._handle_audio_frame(b"\x00\x01", "192.168.1.99")
        speaker.play_raw.assert_not_called()

    def test_handle_audio_frame_without_speaker_is_safe(self):
        from intercom.intercom_manager import IntercomState
        manager = self._make_manager(speaker=None)
        manager._state = IntercomState.ACTIVE
        manager._active_peer_ip = "192.168.1.50"
        try:
            manager._handle_audio_frame(b"\x00\x01", "192.168.1.50")
        except Exception as exc:
            self.fail(f"_handle_audio_frame raised unexpectedly: {exc}")

    def test_handle_audio_frame_speaker_error_is_handled(self):
        from intercom.intercom_manager import IntercomState
        speaker = MagicMock()
        speaker.play_raw.side_effect = RuntimeError("audio device busy")
        manager = self._make_manager(speaker=speaker)
        manager._state = IntercomState.ACTIVE
        manager._active_peer_ip = "192.168.1.50"
        try:
            manager._handle_audio_frame(b"\x00\x01", "192.168.1.50")
        except Exception as exc:
            self.fail(f"_handle_audio_frame raised unexpectedly: {exc}")

    def test_audio_send_loop_sends_microphone_frames(self):
        from intercom.intercom_manager import IntercomState
        microphone = MagicMock()
        microphone.is_open = True
        microphone.read_frame.return_value = b"\x00" * 1024

        manager = self._make_manager(microphone=microphone)
        manager._udp_socket = MagicMock()
        manager._active_peer_ip = "192.168.1.50"
        manager._state = IntercomState.ACTIVE

        async def _run():
            task = asyncio.create_task(manager._audio_send_loop())
            await asyncio.sleep(0.05)
            manager._state = IntercomState.IDLE
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        run_async(_run())
        microphone.read_frame.assert_called()
        manager._udp_socket.sendto.assert_called()

    def test_audio_send_loop_idles_without_microphone(self):
        from intercom.intercom_manager import IntercomState
        manager = self._make_manager(microphone=None)
        manager._state = IntercomState.ACTIVE

        async def _run():
            task = asyncio.create_task(manager._audio_send_loop())
            await asyncio.sleep(0.05)
            manager._state = IntercomState.IDLE
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        try:
            run_async(_run())
        except Exception as exc:
            self.fail(f"_audio_send_loop raised unexpectedly: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# IntercomManager — socket lifecycle
# ─────────────────────────────────────────────────────────────────────────────

class TestIntercomManagerSockets(unittest.TestCase):
    """Tests for start()/stop() UDP socket lifecycle."""

    def setUp(self):
        patcher = patch("core.ws_hub.ws_hub.broadcast", new_callable=AsyncMock)
        self.mock_broadcast = patcher.start()
        self.addCleanup(patcher.stop)

    def test_start_opens_socket_and_stop_closes_it(self):
        from intercom.intercom_manager import IntercomManager
        manager = IntercomManager()
        run_async(manager.start())
        self.assertIsNotNone(manager._udp_socket)
        self.assertIsNotNone(manager._listen_task)

        run_async(manager.stop())
        self.assertIsNone(manager._udp_socket)
        self.assertIsNone(manager._listen_task)


# ─────────────────────────────────────────────────────────────────────────────
# /api/vortex/v1/intercom
# ─────────────────────────────────────────────────────────────────────────────

class TestIntercomAPI(unittest.TestCase):
    """Tests for core/intercom_api.py — /api/vortex/v1/intercom routes."""

    def setUp(self):
        patcher = patch("core.ws_hub.ws_hub.broadcast", new_callable=AsyncMock)
        self.mock_broadcast = patcher.start()
        self.addCleanup(patcher.stop)

        from intercom.intercom_manager import IntercomManager
        from intercom.unit_discovery import UnitDiscovery
        from core.intercom_api import router, set_intercom_manager

        self.manager = IntercomManager()
        set_intercom_manager(self.manager)
        self.addCleanup(set_intercom_manager, None)
        self.addCleanup(lambda: run_async(self.manager._reset_to_idle()))

        UnitDiscovery._peers.clear()
        self.addCleanup(UnitDiscovery._peers.clear)

        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_get_intercom_state_idle(self):
        resp = self.client.get("/api/vortex/v1/intercom")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"state": "idle", "peer": None})

    def test_list_peers(self):
        from intercom.unit_discovery import UnitDiscovery
        UnitDiscovery._peers["vortex-bedroom-01"] = PEER

        resp = self.client.get("/api/vortex/v1/intercom/peers")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["peers"], [PEER])

    def test_place_call_returns_202(self):
        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
            resp = self.client.post(
                "/api/vortex/v1/intercom/call", json={"peer_unit_id": "vortex-bedroom-01"}
            )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["state"], "calling")

    def test_place_call_requires_peer_unit_id(self):
        resp = self.client.post("/api/vortex/v1/intercom/call", json={"peer_unit_id": ""})
        self.assertEqual(resp.status_code, 422)

    def test_place_call_unknown_peer_returns_409(self):
        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=None):
            resp = self.client.post(
                "/api/vortex/v1/intercom/call", json={"peer_unit_id": "vortex-unknown"}
            )
        self.assertEqual(resp.status_code, 409)

    def test_place_call_while_busy_returns_409(self):
        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
            self.client.post("/api/vortex/v1/intercom/call", json={"peer_unit_id": "vortex-bedroom-01"})
            resp = self.client.post("/api/vortex/v1/intercom/call", json={"peer_unit_id": "vortex-bedroom-01"})
        self.assertEqual(resp.status_code, 409)

    def test_answer_without_ringing_returns_409(self):
        resp = self.client.post("/api/vortex/v1/intercom/answer")
        self.assertEqual(resp.status_code, 409)

    def test_decline_without_ringing_returns_409(self):
        resp = self.client.post("/api/vortex/v1/intercom/decline")
        self.assertEqual(resp.status_code, 409)

    def test_hang_up_when_idle_returns_200(self):
        resp = self.client.delete("/api/vortex/v1/intercom")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"state": "idle", "peer": None})

    def test_full_call_flow(self):
        with patch("intercom.unit_discovery.UnitDiscovery.get_peer", return_value=PEER):
            resp = self.client.post(
                "/api/vortex/v1/intercom/call", json={"peer_unit_id": "vortex-bedroom-01"}
            )
        self.assertEqual(resp.json()["state"], "calling")

        # Simulate the peer accepting the call
        run_async(self.manager._activate_call())
        resp = self.client.get("/api/vortex/v1/intercom")
        self.assertEqual(resp.json()["state"], "active")

        resp = self.client.delete("/api/vortex/v1/intercom")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["state"], "idle")

    def test_incoming_call_can_be_answered_and_ended(self):
        async def _run():
            self.manager._handle_control_message(_control_payload("call_request"), "192.168.1.50")
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        run_async(_run())
        self.assertEqual(self.manager.state, "ringing")

        resp = self.client.post("/api/vortex/v1/intercom/answer")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["state"], "active")

        resp = self.client.delete("/api/vortex/v1/intercom")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["state"], "idle")

    def test_incoming_call_can_be_declined(self):
        async def _run():
            self.manager._handle_control_message(_control_payload("call_request"), "192.168.1.50")
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        run_async(_run())
        self.assertEqual(self.manager.state, "ringing")

        resp = self.client.post("/api/vortex/v1/intercom/decline")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["state"], "idle")


class TestIntercomAPIUnavailable(unittest.TestCase):
    """The /intercom routes (except /peers) should respond 503 when no IntercomManager is wired."""

    def setUp(self):
        from core.intercom_api import router, set_intercom_manager
        set_intercom_manager(None)
        self.addCleanup(set_intercom_manager, None)

        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_get_state_503_without_manager(self):
        resp = self.client.get("/api/vortex/v1/intercom")
        self.assertEqual(resp.status_code, 503)

    def test_call_503_without_manager(self):
        resp = self.client.post("/api/vortex/v1/intercom/call", json={"peer_unit_id": "vortex-bedroom-01"})
        self.assertEqual(resp.status_code, 503)

    def test_answer_503_without_manager(self):
        resp = self.client.post("/api/vortex/v1/intercom/answer")
        self.assertEqual(resp.status_code, 503)

    def test_decline_503_without_manager(self):
        resp = self.client.post("/api/vortex/v1/intercom/decline")
        self.assertEqual(resp.status_code, 503)

    def test_hang_up_503_without_manager(self):
        resp = self.client.delete("/api/vortex/v1/intercom")
        self.assertEqual(resp.status_code, 503)

    def test_peers_works_without_manager(self):
        resp = self.client.get("/api/vortex/v1/intercom/peers")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("peers", resp.json())


if __name__ == "__main__":
    unittest.main()
