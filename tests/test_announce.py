"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_announce.py
Purpose:     Unit tests for multi-room announcements / "Drop In" broadcasts —
             AnnouncementSession (core/announce.py) and the
             /api/vortex/v1/announce REST API (core/announce_api.py),
             including media ducking via DeviceControl and chime playback.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-12
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def run_async(coro):
    """Run an async coroutine synchronously in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────────
# AnnouncementSession
# ─────────────────────────────────────────────────────────────────────────────

class TestAnnouncementSession(unittest.TestCase):
    """Tests for core/announce.py — AnnouncementSession."""

    def setUp(self):
        patcher = patch("core.ws_hub.ws_hub.broadcast", new_callable=AsyncMock)
        self.mock_broadcast = patcher.start()
        self.addCleanup(patcher.stop)

    def _make_session(self, device_control=None, audio_manager=None):
        from core.announce import AnnouncementSession
        return AnnouncementSession(device_control=device_control, audio_manager=audio_manager)

    def _make_device_control(self, players=None):
        dc = MagicMock()
        dc.get_all_media_players = AsyncMock(return_value=players or [])
        dc.set_media_volume = AsyncMock(return_value=True)
        return dc

    def test_announce_returns_expected_shape(self):
        session = self._make_session()
        announcement = run_async(session.announce("Dinner's ready!", source="Kitchen Vortex"))
        self.assertEqual(announcement["message"], "Dinner's ready!")
        self.assertEqual(announcement["source"], "Kitchen Vortex")
        self.assertEqual(announcement["priority"], "normal")
        self.assertIsNone(announcement["audio_url"])
        self.assertIn("id", announcement)
        self.assertIn("timestamp", announcement)

    def test_announce_broadcasts_event(self):
        session = self._make_session()
        announcement = run_async(session.announce("Hello house"))
        self.mock_broadcast.assert_any_call({"type": "announcement", "announcement": announcement})

    def test_announce_plays_intercom_chime(self):
        audio_manager = MagicMock()
        session = self._make_session(audio_manager=audio_manager)
        run_async(session.announce("Hello house"))
        audio_manager.play_chime.assert_called_once_with("intercom")

    def test_chime_failure_does_not_raise(self):
        audio_manager = MagicMock()
        audio_manager.play_chime.side_effect = RuntimeError("speaker offline")
        session = self._make_session(audio_manager=audio_manager)
        try:
            run_async(session.announce("Hello house"))
        except Exception as exc:
            self.fail(f"announce() raised unexpectedly: {exc}")

    def test_no_audio_manager_is_safe(self):
        session = self._make_session(audio_manager=None)
        try:
            run_async(session.announce("Hello house"))
        except Exception as exc:
            self.fail(f"announce() raised unexpectedly: {exc}")

    # ── Media ducking ────────────────────────────────────────────────────────

    def test_announce_ducks_only_playing_media_players(self):
        from core.constants import ANNOUNCEMENT_DUCK_VOLUME_LEVEL
        dc = self._make_device_control(players=[
            {"entity_id": "media_player.living_room", "state": "playing", "attributes": {"volume_level": 0.6}},
            {"entity_id": "media_player.bedroom", "state": "paused", "attributes": {"volume_level": 0.5}},
        ])
        session = self._make_session(device_control=dc)
        run_async(session.announce("Hello house", duration_seconds=0.01))
        dc.set_media_volume.assert_any_call("media_player.living_room", ANNOUNCEMENT_DUCK_VOLUME_LEVEL)

    def test_restores_media_after_duration(self):
        dc = self._make_device_control(players=[
            {"entity_id": "media_player.living_room", "state": "playing", "attributes": {"volume_level": 0.6}},
        ])
        session = self._make_session(device_control=dc)
        run_async(session.announce("Hello house", duration_seconds=0.01))
        run_async(asyncio.sleep(0.05))
        dc.set_media_volume.assert_any_call("media_player.living_room", 0.6)

    def test_no_device_control_skips_ducking(self):
        session = self._make_session(device_control=None)
        try:
            run_async(session.announce("Hello house", duration_seconds=0.01))
            run_async(asyncio.sleep(0.05))
        except Exception as exc:
            self.fail(f"announce() raised unexpectedly: {exc}")

    def test_get_all_media_players_error_is_handled(self):
        dc = self._make_device_control()
        dc.get_all_media_players = AsyncMock(side_effect=RuntimeError("HA unreachable"))
        session = self._make_session(device_control=dc)
        try:
            run_async(session.announce("Hello house", duration_seconds=0.01))
        except Exception as exc:
            self.fail(f"announce() raised unexpectedly: {exc}")

    def test_overlapping_announcements_do_not_double_duck(self):
        from core.constants import ANNOUNCEMENT_DUCK_VOLUME_LEVEL
        dc = self._make_device_control(players=[
            {"entity_id": "media_player.living_room", "state": "playing", "attributes": {"volume_level": 0.6}},
        ])
        session = self._make_session(device_control=dc)
        run_async(session.announce("First", duration_seconds=10))
        run_async(session.announce("Second", duration_seconds=0.01))

        duck_calls = [
            c for c in dc.set_media_volume.call_args_list
            if c.args == ("media_player.living_room", ANNOUNCEMENT_DUCK_VOLUME_LEVEL)
        ]
        self.assertEqual(len(duck_calls), 1)

        run_async(asyncio.sleep(0.05))
        dc.set_media_volume.assert_any_call("media_player.living_room", 0.6)

    # ── Duration estimation ─────────────────────────────────────────────────

    def test_estimate_duration_short_message(self):
        from core.constants import ANNOUNCEMENT_DEFAULT_DURATION_SECONDS
        from core.announce import _estimate_duration
        self.assertEqual(_estimate_duration("Hi"), ANNOUNCEMENT_DEFAULT_DURATION_SECONDS)

    def test_estimate_duration_long_message_capped(self):
        from core.constants import ANNOUNCEMENT_MAX_DURATION_SECONDS
        from core.announce import _estimate_duration
        long_message = " ".join(["word"] * 500)
        self.assertEqual(_estimate_duration(long_message), ANNOUNCEMENT_MAX_DURATION_SECONDS)


# ─────────────────────────────────────────────────────────────────────────────
# /api/vortex/v1/announce
# ─────────────────────────────────────────────────────────────────────────────

class TestAnnounceAPI(unittest.TestCase):
    """Tests for core/announce_api.py — /api/vortex/v1/announce routes."""

    def setUp(self):
        patcher = patch("core.ws_hub.ws_hub.broadcast", new_callable=AsyncMock)
        self.mock_broadcast = patcher.start()
        self.addCleanup(patcher.stop)

        from core.announce import AnnouncementSession
        from core.announce_api import router, set_announcement_session

        self.session = AnnouncementSession()
        set_announcement_session(self.session)
        self.addCleanup(set_announcement_session, None)

        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_post_announcement_returns_202(self):
        resp = self.client.post(
            "/api/vortex/v1/announce",
            json={"message": "Dinner's ready!", "source": "Kitchen Vortex"},
        )
        self.assertEqual(resp.status_code, 202)
        data = resp.json()
        self.assertEqual(data["message"], "Dinner's ready!")
        self.assertEqual(data["source"], "Kitchen Vortex")
        self.assertEqual(data["priority"], "normal")

    def test_post_announcement_with_urgent_priority(self):
        resp = self.client.post(
            "/api/vortex/v1/announce",
            json={"message": "Front door is unlocked!", "priority": "urgent"},
        )
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.json()["priority"], "urgent")

    def test_post_announcement_requires_message(self):
        resp = self.client.post("/api/vortex/v1/announce", json={"message": ""})
        self.assertEqual(resp.status_code, 422)

    def test_post_announcement_rejects_oversized_message(self):
        from core.constants import ANNOUNCEMENT_MAX_MESSAGE_LENGTH
        resp = self.client.post(
            "/api/vortex/v1/announce",
            json={"message": "x" * (ANNOUNCEMENT_MAX_MESSAGE_LENGTH + 1)},
        )
        self.assertEqual(resp.status_code, 422)

    def test_post_announcement_rejects_invalid_priority(self):
        resp = self.client.post(
            "/api/vortex/v1/announce",
            json={"message": "Hello", "priority": "loud"},
        )
        self.assertEqual(resp.status_code, 422)

    def test_post_announcement_rejects_invalid_duration(self):
        from core.constants import ANNOUNCEMENT_MAX_DURATION_SECONDS
        resp = self.client.post(
            "/api/vortex/v1/announce",
            json={"message": "Hello", "duration_seconds": 0},
        )
        self.assertEqual(resp.status_code, 422)

        resp = self.client.post(
            "/api/vortex/v1/announce",
            json={"message": "Hello", "duration_seconds": ANNOUNCEMENT_MAX_DURATION_SECONDS + 1},
        )
        self.assertEqual(resp.status_code, 422)


class TestAnnounceAPIUnavailable(unittest.TestCase):
    """The /announce route should respond 503 when no AnnouncementSession is wired."""

    def setUp(self):
        from core.announce_api import router, set_announcement_session
        set_announcement_session(None)
        self.addCleanup(set_announcement_session, None)

        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_post_announcement_503_without_session(self):
        resp = self.client.post("/api/vortex/v1/announce", json={"message": "Hello"})
        self.assertEqual(resp.status_code, 503)


if __name__ == "__main__":
    unittest.main()
