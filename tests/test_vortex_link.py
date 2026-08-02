"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_vortex_link.py
Purpose:     Tests for connectivity/vortex_link.py — the uplink to River Song.

             These are protocol-match tests. The failure this file exists to
             catch is not "the code crashed", it is "both sides work perfectly
             and disagree about a field name" — which is exactly how the
             device grid, the orb and the offline voice all came to be built
             and unreachable.

             Frame shapes here are checked against RiverSongAI's
             api/routes/vortex.py and core/vortex_hub.py. If either moves,
             these should fail before a real unit does.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import base64
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from connectivity.vortex_link import VortexLink, _ws_url


def run(coro):
    """Run a coroutine on the suite's shared event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestUplinkURL(unittest.TestCase):
    """The unit dials out; the URL has to be derivable from the HTTP base."""

    def test_http_becomes_ws(self):
        url = _ws_url("http://riversong.local:8000", "vortex-abc")
        self.assertTrue(url.startswith("ws://riversong.local:8000/api/vortex/ws"))

    def test_https_becomes_wss(self):
        self.assertTrue(
            _ws_url("https://river.example", "u").startswith("wss://river.example"))

    def test_the_unit_id_rides_the_query_string(self):
        """
        It lets River Song refuse an unknown unit BEFORE completing the
        handshake, rather than accepting a socket it is about to discard.
        """
        self.assertIn("unit_id=vortex-abc",
                      _ws_url("http://r.local", "vortex-abc"))

    def test_a_trailing_slash_does_not_double_up(self):
        self.assertNotIn("//api", _ws_url("http://r.local/", "u").replace("://", ""))

    def test_an_unusable_base_is_rejected_loudly(self):
        with self.assertRaises(ValueError):
            _ws_url("ftp://r.local", "u")


class LinkTestCase(unittest.TestCase):
    """Base — a link with stubbed subsystems and no real socket."""

    def setUp(self):
        patcher = patch("connectivity.vortex_link.ws_hub.broadcast",
                        new_callable=AsyncMock)
        self.broadcast = patcher.start()
        self.addCleanup(patcher.stop)

        self.surfaces = MagicMock()
        self.surfaces.push = AsyncMock()
        self.surfaces.withdraw = AsyncMock()
        self.media = MagicMock()
        for name in ("play", "pause", "resume", "stop_playback",
                     "next_track", "previous_track", "set_volume"):
            setattr(self.media, name, AsyncMock())
        self.audio = MagicMock()

        self.link = VortexLink()
        self.link.attach(surface_store=self.surfaces, media_player=self.media,
                         audio_manager=self.audio)

    def _relayed(self):
        """Frame types forwarded verbatim to the browser."""
        return [c.args[0].get("type") for c in self.broadcast.call_args_list]


class TestSurfaceFrames(LinkTestCase):
    """Cards pushed by River Song must behave like locally posted ones."""

    def test_a_pushed_card_goes_through_the_local_store(self):
        """
        Not straight to the browser: the store is what applies the TTL, the
        priority ordering, the screen wake and the spoken delivery on a Mini.
        """
        run(self.link._dispatch({
            "type": "surface", "id": "bins", "kind": "note",
            "priority": "normal", "title": "Bin day", "ttl_seconds": 600,
        }))
        self.surfaces.push.assert_awaited_once()
        card = self.surfaces.push.await_args.args[0]
        self.assertEqual(card["id"], "bins")
        self.assertEqual(card["title"], "Bin day")

    def test_the_frame_type_is_stripped_from_the_card(self):
        """`type` is envelope, not payload; leaving it in pollutes the store."""
        run(self.link._dispatch({"type": "surface", "id": "a", "kind": "note"}))
        self.assertNotIn("type", self.surfaces.push.await_args.args[0])

    def test_speech_is_passed_so_a_screenless_unit_still_hears_it(self):
        run(self.link._dispatch({
            "type": "surface", "id": "a", "kind": "alert",
            "speech": "The garage is open.",
        }))
        self.assertEqual(self.surfaces.push.await_args.kwargs["speech"],
                         "The garage is open.")

    def test_river_songs_withdraw_maps_onto_the_local_remove(self):
        """
        River Song says `surface_withdraw`; this store and the browser both
        say remove. The rename is deliberate and lives in one place.
        """
        run(self.link._dispatch({"type": "surface_withdraw", "id": "bins"}))
        self.surfaces.withdraw.assert_awaited_once_with("bins")

    def test_a_card_is_not_relayed_raw_to_the_browser(self):
        run(self.link._dispatch({"type": "surface", "id": "a", "kind": "note"}))
        self.assertNotIn("surface", self._relayed())


class TestMediaFrames(LinkTestCase):
    """Music River Song resolved must play on THIS unit's speaker."""

    def test_play_splits_the_url_from_the_display_metadata(self):
        run(self.link._dispatch({
            "type": "media", "action": "play",
            "track": {"url": "http://x/y.mp3", "title": "Song", "artist": "A"},
        }))
        self.media.play.assert_awaited_once()
        url = self.media.play.await_args.args[0]
        meta = self.media.play.await_args.kwargs["metadata"]
        self.assertEqual(url, "http://x/y.mp3")
        self.assertEqual(meta["title"], "Song")
        self.assertNotIn("url", meta)

    def test_a_queue_is_passed_through(self):
        run(self.link._dispatch({
            "type": "media", "action": "play",
            "track": {"url": "http://x/1.mp3"},
            "queue": [{"url": "http://x/2.mp3"}],
        }))
        self.assertEqual(len(self.media.play.await_args.kwargs["queue"]), 1)

    def test_play_without_a_url_is_ignored_rather_than_raising(self):
        run(self.link._dispatch({"type": "media", "action": "play",
                                 "track": {"title": "no url"}}))
        self.media.play.assert_not_awaited()

    def test_stop_stops_playback_and_does_not_shut_the_player_down(self):
        """
        stop() tears mpv down entirely and the unit goes silent until it is
        restarted. The transport command is stop_playback().
        """
        run(self.link._dispatch({"type": "media", "action": "stop"}))
        self.media.stop_playback.assert_awaited_once()
        self.media.stop.assert_not_called()

    def test_transport_actions_reach_the_player(self):
        for action, method in (("pause", "pause"), ("resume", "resume"),
                               ("next", "next_track"),
                               ("previous", "previous_track")):
            run(self.link._dispatch({"type": "media", "action": action}))
            getattr(self.media, method).assert_awaited()

    def test_an_unknown_action_is_ignored(self):
        run(self.link._dispatch({"type": "media", "action": "teleport"}))
        self.media.play.assert_not_awaited()


class TestUtterance(LinkTestCase):
    """Captured voice goes up the socket, not to a REST endpoint that 404s."""

    def _connect(self):
        self.link._connected = True
        self.link._socket = MagicMock()
        self.link._socket.send = AsyncMock()
        return self.link._socket

    def _frames(self, socket):
        return [json.loads(c.args[0]) for c in socket.send.await_args_list]

    def test_a_short_command_is_one_final_frame(self):
        socket = self._connect()
        run(self.link.send_utterance(b"x" * 1000))
        frames = self._frames(socket)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0]["type"], "audio_chunk")
        self.assertTrue(frames[0]["final"])

    def test_audio_is_base64_encoded(self):
        socket = self._connect()
        run(self.link.send_utterance(b"RAWPCM"))
        self.assertEqual(base64.b64decode(self._frames(socket)[0]["data"]), b"RAWPCM")

    def test_a_long_command_is_split_and_only_the_last_frame_is_final(self):
        """
        Written for the fixed server. River Song currently discards non-final
        chunks, so long commands are dropped there — but the moment it
        accumulates them, this starts working with no change here.
        """
        from connectivity.vortex_link import AUDIO_CHUNK_BYTES
        socket = self._connect()
        run(self.link.send_utterance(b"y" * (AUDIO_CHUNK_BYTES * 2 + 10)))
        frames = self._frames(socket)
        self.assertEqual(len(frames), 3)
        self.assertEqual([f["final"] for f in frames], [False, False, True])

    def test_no_frame_exceeds_the_servers_limit(self):
        """River Song rejects a decoded chunk over 128 KiB outright."""
        from connectivity.vortex_link import AUDIO_CHUNK_BYTES
        socket = self._connect()
        run(self.link.send_utterance(b"z" * (AUDIO_CHUNK_BYTES * 3)))
        for frame in self._frames(socket):
            self.assertLessEqual(len(base64.b64decode(frame["data"])), 128 * 1024)

    def test_the_whole_utterance_survives_the_split(self):
        from connectivity.vortex_link import AUDIO_CHUNK_BYTES
        socket = self._connect()
        audio = bytes(range(256)) * (AUDIO_CHUNK_BYTES // 128)
        run(self.link.send_utterance(audio))
        rejoined = b"".join(base64.b64decode(f["data"]) for f in self._frames(socket))
        self.assertEqual(rejoined, audio)

    def test_sending_with_no_uplink_reports_it_was_never_heard(self):
        self.assertFalse(run(self.link.send_utterance(b"x")))

    def test_empty_audio_is_not_sent(self):
        socket = self._connect()
        self.assertFalse(run(self.link.send_utterance(b"")))
        socket.send.assert_not_awaited()

    def test_a_drop_mid_utterance_reports_failure(self):
        """Half a command reaching River Song is worse than none."""
        from connectivity.vortex_link import AUDIO_CHUNK_BYTES
        socket = self._connect()
        socket.send.side_effect = [None, RuntimeError("dropped")]
        self.assertFalse(run(self.link.send_utterance(b"a" * (AUDIO_CHUNK_BYTES * 2))))


class TestReplyTracking(LinkTestCase):
    """Telling 'she answered' apart from 'the server went quiet'."""

    def test_frames_river_initiates_count_as_a_reply(self):
        for kind in ("presence", "amplitude", "audio", "surface"):
            before = self.link.last_reply_at
            run(self.link._dispatch({"type": kind}))
            self.assertGreater(self.link.last_reply_at, before, kind)

    def test_routine_feed_updates_do_not_count(self):
        """They arrive on a timer and would make a silent server look alive."""
        run(self.link._dispatch({"type": "devices_update", "data": []}))
        self.assertEqual(self.link.last_reply_at, 0.0)


class TestPresenceOnAScreenlessUnit(LinkTestCase):
    """
    River Song reports some failures as presence and nothing else.

    An over-long utterance comes back as state `error` with a caption. On a
    Hub that lands on the orb. On a Mini it lands nowhere — no browser, no
    orb — so it has to be spoken or the user gets silence and no explanation.
    """

    def _dispatch_error(self, has_screen, caption="Too long"):
        speak = AsyncMock()
        with patch("core.presenter.presenter") as presenter, \
             patch("core.voice.voice.speak", speak):
            presenter.has_screen = has_screen
            run(self.link._dispatch({
                "type": "presence",
                "data": {"state": "error", "caption": caption},
            }))
        return speak

    def test_a_screenless_unit_speaks_the_failure(self):
        speak = self._dispatch_error(has_screen=False)
        speak.assert_awaited_once()
        self.assertEqual(speak.await_args.args[0], "Too long")

    def test_a_screened_unit_stays_quiet_and_shows_it_instead(self):
        self._dispatch_error(has_screen=True).assert_not_awaited()

    def test_ordinary_states_are_never_narrated(self):
        """Speaking every transition would make a Mini unbearable."""
        speak = AsyncMock()
        with patch("core.presenter.presenter") as presenter, \
             patch("core.voice.voice.speak", speak):
            presenter.has_screen = False
            for state in ("listening", "thinking", "speaking", "idle"):
                run(self.link._dispatch({"type": "presence",
                                         "data": {"state": state,
                                                  "caption": "working"}}))
        speak.assert_not_awaited()

    def test_an_error_with_no_caption_says_nothing(self):
        """There is nothing useful to say, and inventing wording would lie."""
        self._dispatch_error(has_screen=False, caption="").assert_not_awaited()

    def test_the_frame_still_reaches_the_screen_either_way(self):
        self._dispatch_error(has_screen=False)
        self.assertIn("presence", self._relayed())


class TestReplicaRetunesTheWakeWord(LinkTestCase):
    """
    The wake word is set in River Song, not on the unit.

    There is no settings screen on a Vortex panel, so if these two fields do
    not arrive over the replica the only way to change them is SSHing into a
    Pi and editing JSON — which is exactly what the product promises you never
    have to do.
    """

    def setUp(self):
        super().setUp()
        self.detector = MagicMock()
        self.detector.set_wake_word = AsyncMock(return_value=True)
        self.detector.set_threshold = MagicMock(return_value=True)
        self.link.attach(wake_word=self.detector)

    def test_a_new_phrase_retunes_the_detector(self):
        run(self.link._dispatch({"type": "replica", "wake_word": "hey river"}))
        self.detector.set_wake_word.assert_awaited_once_with("hey river")

    def test_the_threshold_arrives_in_the_units_own_settings(self):
        """Per unit, not per household — rooms differ."""
        run(self.link._dispatch({
            "type": "replica", "settings": {"wake_word_threshold": 0.8},
        }))
        self.detector.set_threshold.assert_called_once_with(0.8)

    def test_a_top_level_threshold_is_also_accepted(self):
        """Tolerated so a flatter payload shape does not silently do nothing."""
        run(self.link._dispatch({"type": "replica", "wake_word_threshold": 0.7}))
        self.detector.set_threshold.assert_called_once_with(0.7)

    def test_a_replica_without_either_field_changes_nothing(self):
        run(self.link._dispatch({"type": "replica", "devices": []}))
        self.detector.set_wake_word.assert_not_awaited()
        self.detector.set_threshold.assert_not_called()

    def test_the_replica_still_reaches_the_screen(self):
        run(self.link._dispatch({"type": "replica", "wake_word": "hey river"}))
        self.assertIn("replica", self._relayed())

    def test_a_detector_that_rejects_the_phrase_does_not_break_the_uplink(self):
        self.detector.set_wake_word = AsyncMock(side_effect=RuntimeError("no model"))
        run(self.link._dispatch({"type": "replica", "wake_word": "hey nonsense"}))
        self.assertIn("replica", self._relayed())

    def test_a_unit_with_no_detector_ignores_both(self):
        """A Mini with a broken mic still has to take the rest of the replica."""
        link = VortexLink()
        with patch("connectivity.vortex_link.ws_hub.broadcast", new_callable=AsyncMock):
            run(link._dispatch({"type": "replica", "wake_word": "hey river",
                                "settings": {"wake_word_threshold": 0.9}}))


class TestRelayedFrames(LinkTestCase):
    """
    Frames the browser already understands go straight through.

    Translating them here would create a second vocabulary free to drift from
    the one App.jsx handles, which is the bug class this whole file guards.
    """

    def test_presence_and_amplitude_reach_the_browser_untouched(self):
        run(self.link._dispatch({"type": "presence", "data": {"state": "speaking"}}))
        run(self.link._dispatch({"type": "amplitude", "value": 0.4}))
        self.assertEqual(self._relayed(), ["presence", "amplitude"])

    def test_the_device_and_camera_feeds_are_relayed(self):
        """The three feeds whose absence left those screens permanently empty."""
        for kind in ("devices_update", "cameras_update", "notifications_update"):
            run(self.link._dispatch({"type": kind, "data": []}))
        self.assertEqual(self._relayed(),
                         ["devices_update", "cameras_update", "notifications_update"])

    def test_an_unknown_frame_is_dropped_quietly(self):
        run(self.link._dispatch({"type": "something_new", "x": 1}))
        self.assertEqual(self._relayed(), [])

    def test_a_pong_is_not_relayed(self):
        run(self.link._dispatch({"type": "pong", "t": 1}))
        self.assertEqual(self._relayed(), [])


class TestAudioFrames(LinkTestCase):
    """TTS River Song pushes rather than returns."""

    def test_base64_audio_is_decoded_and_played(self):
        run(self.link._dispatch({
            "type": "audio", "format": "wav",
            "audio": base64.b64encode(b"RIFFwav").decode("ascii"),
        }))
        self.audio.speaker.play.assert_called_once()
        self.assertEqual(self.audio.speaker.play.call_args.args[0], b"RIFFwav")

    def test_malformed_audio_does_not_take_the_uplink_down(self):
        run(self.link._dispatch({"type": "audio", "audio": "!!!not base64!!!"}))
        self.audio.speaker.play.assert_not_called()

    def test_an_empty_audio_frame_is_ignored(self):
        run(self.link._dispatch({"type": "audio", "audio": ""}))
        self.audio.speaker.play.assert_not_called()


class TestSending(LinkTestCase):
    """Unit → server frames."""

    def _connect(self):
        self.link._connected = True
        self.link._socket = MagicMock()
        self.link._socket.send = AsyncMock()
        return self.link._socket

    def test_a_frame_carries_its_type_alongside_the_payload(self):
        """River Song's frames are flat — {"type": ..., ...payload}."""
        socket = self._connect()
        run(self.link.send("state", {"state": "listening"}))
        sent = json.loads(socket.send.await_args.args[0])
        self.assertEqual(sent, {"type": "state", "state": "listening"})

    def test_sending_while_offline_reports_failure_rather_than_raising(self):
        """Offline is a normal state for a unit, not an error to stop for."""
        self.assertFalse(run(self.link.send("state", {"state": "idle"})))

    def test_a_broken_socket_reports_failure_rather_than_raising(self):
        socket = self._connect()
        socket.send.side_effect = RuntimeError("pipe closed")
        self.assertFalse(run(self.link.send("ping")))

    def test_camera_state_is_reported_under_the_key_river_song_reads(self):
        socket = self._connect()
        run(self.link.report_camera({"fitted": True, "purposes": {}}))
        sent = json.loads(socket.send.await_args.args[0])
        self.assertEqual(sent["type"], "camera_state")
        self.assertTrue(sent["camera"]["fitted"])


class TestLifecycle(LinkTestCase):
    """Connecting, and not connecting."""

    def test_an_unpaired_unit_does_not_dial_out(self):
        """There is no token to authenticate with, so there is nothing to try."""
        with patch("connectivity.vortex_link.config") as cfg:
            cfg.get.side_effect = lambda k, d=None: {"river_song_api_key": ""}.get(k, d)
            run(self.link.start())
        self.assertFalse(self.link._running)

    def test_stop_is_safe_before_start(self):
        run(self.link.stop())
        self.assertFalse(self.link.connected)

    def test_disconnection_tells_the_screen(self):
        self.link._connected = True
        run(self.link._on_disconnected())
        self.assertIn("uplink", self._relayed())
        self.assertFalse(self.broadcast.call_args.args[0]["connected"])

    def test_a_disconnect_that_was_never_connected_says_nothing(self):
        """Otherwise every reconnect attempt would flap the banner."""
        run(self.link._on_disconnected())
        self.assertEqual(self._relayed(), [])


class TestAPIClientWiring(unittest.TestCase):
    """
    The REST half of the same contract.

    These call the real client rather than mocking it. Mocking APIClient is
    what let a broken httpx.Timeout — invalid in FOUR methods — sit behind a
    full suite of passing tests: every caller was stubbed, so nothing ever
    constructed one.
    """

    def _client(self):
        from connectivity.api_client import APIClient
        settings = {"river_song_api_url": "http://riversong.local",
                    "river_song_api_key": "tok", "unit_id": "vortex-1"}
        with patch("core.config.config.get",
                   side_effect=lambda k, d=None: settings.get(k, d)):
            return APIClient()

    def test_the_unit_token_header_river_song_actually_reads_is_sent(self):
        """
        River Song's _require_unit reads X-Unit-Token. Authorization: Bearer,
        which is what this client used to send alone, is read by no route on
        that side — every call from a real unit was rejected.
        """
        self.assertEqual(self._client()._headers["X-Unit-Token"], "tok")

    def test_every_timeout_this_client_builds_is_valid(self):
        """
        httpx raises at call time, not import time, so an invalid timeout
        looks exactly like an unreachable server until you run it.
        """
        from connectivity.api_client import _timeout
        for kwargs in ({}, {"read": 5.0}, {"read": 120.0, "write": 120.0}):
            t = _timeout(**kwargs)
            for field in ("connect", "read", "write", "pool"):
                self.assertIsNotNone(getattr(t, field), f"{field} unset for {kwargs}")

    def test_synthesize_speech_exists_under_the_name_voice_probes_for(self):
        """
        core/voice.py does getattr(client, "synthesize_speech") and falls
        through silently when it is absent. A rename here would take River's
        voice away across the whole house without one test failing.
        """
        self.assertTrue(callable(getattr(self._client(), "synthesize_speech", None)))

    def test_empty_text_never_reaches_the_network(self):
        client = self._client()
        self.assertIsNone(run(client.synthesize_speech("")))
        self.assertIsNone(run(client.synthesize_speech("   ")))


class TestMissingSubsystems(unittest.TestCase):
    """A Mini has no screen; a unit with no speaker has no player."""

    def setUp(self):
        patcher = patch("connectivity.vortex_link.ws_hub.broadcast",
                        new_callable=AsyncMock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_frames_for_absent_subsystems_are_no_ops(self):
        link = VortexLink()
        for frame in ({"type": "surface", "id": "a"},
                      {"type": "surface_withdraw", "id": "a"},
                      {"type": "media", "action": "play",
                       "track": {"url": "http://x"}},
                      {"type": "audio", "audio": base64.b64encode(b"x").decode()}):
            run(link._dispatch(frame))  # must not raise


if __name__ == "__main__":
    unittest.main()
