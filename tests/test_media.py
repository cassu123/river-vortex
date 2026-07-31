"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_media.py
Purpose:     Tests for audio/media_player.py and core/media_api.py.

             mpv itself is mocked out — what is under test is the transport
             state machine, the queue, and ducking, since those are what the
             UI and River's voice commands both depend on.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from audio.media_player import MediaPlayer, MediaPlayerError, PlaybackState
from core import media_api


def run_async(coro):
    """Run a coroutine on the suite's shared event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


def make_player(on_change=None):
    """A MediaPlayer that believes mpv is running, without launching it."""
    player = MediaPlayer(on_change=on_change)
    player._available = True
    player._proc = object()          # stands in for the mpv process
    player._socket_path = "/tmp/not-a-real-socket"
    return player


class TestTransport(unittest.TestCase):
    """Play, pause, resume, stop."""

    def setUp(self):
        p = patch.object(MediaPlayer, "_command", new_callable=AsyncMock)
        self.command = p.start()
        self.addCleanup(p.stop)
        self.player = make_player()

    def test_play_sets_playing_and_records_metadata(self):
        run_async(self.player.play("http://x/stream.mp3",
                                   {"title": "Dreams", "artist": "Fleetwood Mac"}))
        state = self.player.get_state()
        self.assertEqual(state["state"], PlaybackState.PLAYING)
        self.assertEqual(state["now_playing"]["title"], "Dreams")
        self.assertEqual(state["now_playing"]["url"], "http://x/stream.mp3")

    def test_play_rejects_an_empty_url(self):
        with self.assertRaises(MediaPlayerError):
            run_async(self.player.play("", {}))

    def test_play_fails_clearly_when_playback_is_unavailable(self):
        player = MediaPlayer()
        player._available = False
        with self.assertRaises(MediaPlayerError):
            run_async(player.play("http://x/stream.mp3", {}))

    def test_pause_then_resume_round_trips(self):
        run_async(self.player.play("http://x/a.mp3", {}))
        run_async(self.player.pause())
        self.assertEqual(self.player.get_state()["state"], PlaybackState.PAUSED)
        run_async(self.player.resume())
        self.assertEqual(self.player.get_state()["state"], PlaybackState.PLAYING)

    def test_toggle_follows_current_state(self):
        run_async(self.player.play("http://x/a.mp3", {}))
        run_async(self.player.toggle())
        self.assertEqual(self.player.get_state()["state"], PlaybackState.PAUSED)
        run_async(self.player.toggle())
        self.assertEqual(self.player.get_state()["state"], PlaybackState.PLAYING)

    def test_pause_when_idle_does_nothing(self):
        run_async(self.player.pause())
        self.assertEqual(self.player.get_state()["state"], PlaybackState.IDLE)

    def test_stop_clears_the_track_and_queue(self):
        run_async(self.player.play("http://x/a.mp3", {"title": "A"},
                                   queue=[{"url": "http://x/a.mp3"}]))
        run_async(self.player.stop_playback())
        state = self.player.get_state()
        self.assertEqual(state["state"], PlaybackState.IDLE)
        self.assertEqual(state["now_playing"], {})
        self.assertEqual(state["queue_length"], 0)

    def test_is_playing_reflects_the_transport(self):
        self.assertFalse(self.player.is_playing())
        run_async(self.player.play("http://x/a.mp3", {}))
        self.assertTrue(self.player.is_playing())
        run_async(self.player.pause())
        self.assertFalse(self.player.is_playing())


class TestQueue(unittest.TestCase):
    """Next and previous across a queue."""

    def setUp(self):
        p = patch.object(MediaPlayer, "_command", new_callable=AsyncMock)
        p.start()
        self.addCleanup(p.stop)
        self.player = make_player()
        self.queue = [
            {"url": "http://x/1.mp3", "title": "One"},
            {"url": "http://x/2.mp3", "title": "Two"},
            {"url": "http://x/3.mp3", "title": "Three"},
        ]

    def test_next_advances_through_the_queue(self):
        run_async(self.player.play(self.queue[0]["url"], self.queue[0], queue=self.queue))
        self.assertTrue(run_async(self.player.next_track()))
        self.assertEqual(self.player.get_state()["now_playing"]["title"], "Two")

    def test_next_returns_false_at_the_end(self):
        run_async(self.player.play(self.queue[0]["url"], self.queue[0], queue=self.queue))
        run_async(self.player.next_track())
        run_async(self.player.next_track())
        self.assertFalse(run_async(self.player.next_track()))

    def test_previous_returns_false_at_the_start(self):
        run_async(self.player.play(self.queue[0]["url"], self.queue[0], queue=self.queue))
        self.assertFalse(run_async(self.player.previous_track()))

    def test_previous_steps_back(self):
        run_async(self.player.play(self.queue[0]["url"], self.queue[0], queue=self.queue))
        run_async(self.player.next_track())
        self.assertTrue(run_async(self.player.previous_track()))
        self.assertEqual(self.player.get_state()["now_playing"]["title"], "One")

    def test_state_reports_whether_skipping_is_possible(self):
        run_async(self.player.play(self.queue[0]["url"], self.queue[0], queue=self.queue))
        state = self.player.get_state()
        self.assertTrue(state["has_next"])
        self.assertFalse(state["has_previous"])


class TestDucking(unittest.TestCase):
    """Getting out of the way when River speaks."""

    def setUp(self):
        p = patch.object(MediaPlayer, "_command", new_callable=AsyncMock)
        self.command = p.start()
        self.addCleanup(p.stop)
        self.player = make_player()

    def test_duck_lowers_the_volume(self):
        run_async(self.player.set_volume(80))
        run_async(self.player.duck())
        self.assertTrue(self.player.get_state()["ducked"])
        self.assertEqual(self.command.await_args.args[0][:2],
                         ["set_property", "volume"])
        self.assertLess(self.command.await_args.args[0][2], 80)

    def test_unduck_restores_the_original_volume(self):
        run_async(self.player.set_volume(70))
        run_async(self.player.duck())
        run_async(self.player.unduck())
        self.assertFalse(self.player.get_state()["ducked"])
        self.assertEqual(self.command.await_args.args[0], ["set_property", "volume", 70])

    def test_ducking_twice_does_not_stack_down(self):
        """A timer and an announcement overlapping must not mute the music."""
        run_async(self.player.set_volume(80))
        run_async(self.player.duck())
        first = self.command.await_args.args[0][2]
        run_async(self.player.duck())
        self.assertEqual(self.command.await_args.args[0][2], first)

    def test_volume_set_while_ducked_does_not_undo_the_duck(self):
        run_async(self.player.duck())
        run_async(self.player.set_volume(50))
        self.assertTrue(self.player.get_state()["ducked"])

    def test_volume_is_clamped(self):
        run_async(self.player.set_volume(500))
        self.assertEqual(self.player.get_state()["volume"], 100)
        run_async(self.player.set_volume(-20))
        self.assertEqual(self.player.get_state()["volume"], 0)


class TestStateNotification(unittest.TestCase):
    """The UI follows the player via on_change."""

    def test_transport_changes_are_pushed(self):
        seen = []

        async def on_change(state):
            seen.append(state["state"])

        with patch.object(MediaPlayer, "_command", new_callable=AsyncMock):
            player = make_player(on_change=on_change)
            run_async(player.play("http://x/a.mp3", {}))
            run_async(player.pause())

        self.assertIn(PlaybackState.PLAYING, seen)
        self.assertIn(PlaybackState.PAUSED, seen)

    def test_a_failing_listener_does_not_break_playback(self):
        async def on_change(state):
            raise RuntimeError("socket died")

        with patch.object(MediaPlayer, "_command", new_callable=AsyncMock):
            player = make_player(on_change=on_change)
            run_async(player.play("http://x/a.mp3", {}))
            self.assertEqual(player.get_state()["state"], PlaybackState.PLAYING)


class TestMediaAPI(unittest.TestCase):
    """The endpoints voice and touch both call."""

    def setUp(self):
        p = patch.object(MediaPlayer, "_command", new_callable=AsyncMock)
        p.start()
        self.addCleanup(p.stop)

        self.player = make_player()
        media_api.set_media_player(self.player)
        self.addCleanup(media_api.set_media_player, None)

        app = FastAPI()
        app.include_router(media_api.router)
        self.client = TestClient(app)

    def test_play_starts_a_track(self):
        res = self.client.post("/api/vortex/v1/media/play", json={
            "url": "http://x/a.mp3", "title": "Dreams", "artist": "Fleetwood Mac",
        })
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["state"], PlaybackState.PLAYING)
        self.assertEqual(body["now_playing"]["artist"], "Fleetwood Mac")

    def test_play_requires_a_url(self):
        res = self.client.post("/api/vortex/v1/media/play", json={"title": "No URL"})
        self.assertEqual(res.status_code, 422)

    def test_toggle_pauses_then_resumes(self):
        self.client.post("/api/vortex/v1/media/play", json={"url": "http://x/a.mp3"})
        self.assertEqual(
            self.client.post("/api/vortex/v1/media/toggle").json()["state"],
            PlaybackState.PAUSED)
        self.assertEqual(
            self.client.post("/api/vortex/v1/media/toggle").json()["state"],
            PlaybackState.PLAYING)

    def test_next_at_the_end_of_the_queue_is_a_conflict_not_a_silent_noop(self):
        self.client.post("/api/vortex/v1/media/play", json={"url": "http://x/a.mp3"})
        self.assertEqual(self.client.post("/api/vortex/v1/media/next").status_code, 409)

    def test_volume_is_validated(self):
        self.assertEqual(
            self.client.post("/api/vortex/v1/media/volume", json={"level": 55}).json()["volume"],
            55)
        self.assertEqual(
            self.client.post("/api/vortex/v1/media/volume", json={"level": 900}).status_code,
            422)

    def test_stop_clears_playback(self):
        self.client.post("/api/vortex/v1/media/play", json={"url": "http://x/a.mp3"})
        self.assertEqual(
            self.client.delete("/api/vortex/v1/media").json()["state"], PlaybackState.IDLE)

    def test_endpoints_report_unavailable_without_a_player(self):
        media_api.set_media_player(None)
        self.assertEqual(self.client.get("/api/vortex/v1/media").status_code, 503)


if __name__ == "__main__":
    unittest.main()
