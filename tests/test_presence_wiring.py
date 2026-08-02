"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_presence_wiring.py
Purpose:     Tests for the two seams that were built and never connected:
             AudioManager publishing its state to the presence orb, and the
             voice path speaking rather than beeping when River Song is down.

             Both subsystems already worked in isolation. What is tested here
             is specifically that they are WIRED — the class of bug that does
             not show up in a unit test of either side on its own.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from core.constants import VortexState


def run(coro):
    """Run a coroutine on the suite's shared event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


def make_manager():
    """An AudioManager with all hardware stubbed out."""
    with patch("audio.audio_manager.Microphone"), \
         patch("audio.audio_manager.Speaker"), \
         patch("audio.audio_manager.WakeWordDetector"):
        from audio.audio_manager import AudioManager
        manager = AudioManager()
    manager._running = True
    return manager


class TestPresenceIsPublished(unittest.TestCase):
    """The orb showed idle forever because nothing ever told it otherwise."""

    def setUp(self):
        patcher = patch("audio.audio_manager.ws_hub.broadcast", new_callable=AsyncMock)
        self.broadcast = patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = make_manager()

    def _states_broadcast(self):
        return [c.args[0]["data"]["state"] for c in self.broadcast.call_args_list
                if c.args[0].get("type") == "presence"]

    def test_setting_state_broadcasts_it(self):
        run(self.manager._set_state(VortexState.LISTENING))
        self.assertEqual(self._states_broadcast(), ["LISTENING"])

    def test_the_state_is_also_recorded_locally(self):
        run(self.manager._set_state(VortexState.PROCESSING))
        self.assertEqual(self.manager.state, VortexState.PROCESSING)

    def test_the_enum_name_is_sent_not_a_translation(self):
        """
        The frontend owns the VortexState -> presence mapping. Translating
        here as well would be two tables that could disagree.
        """
        run(self.manager._set_state(VortexState.RESPONDING))
        self.assertEqual(self._states_broadcast(), ["RESPONDING"])

    def test_a_broadcast_failure_does_not_break_the_voice_path(self):
        """Losing the orb is cosmetic; losing the ability to answer is not."""
        self.broadcast.side_effect = RuntimeError("socket died")
        run(self.manager._set_state(VortexState.LISTENING))
        self.assertEqual(self.manager.state, VortexState.LISTENING)


class TestCommandFlowPublishesEveryStage(unittest.TestCase):
    """The full wake-word -> answer cycle, as the orb sees it."""

    def setUp(self):
        patcher = patch("audio.audio_manager.ws_hub.broadcast", new_callable=AsyncMock)
        self.broadcast = patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = make_manager()
        self.manager._microphone.stream_until_silence.return_value = [b"pcm"]

    def _states(self):
        return [c.args[0]["data"]["state"] for c in self.broadcast.call_args_list
                if c.args[0].get("type") == "presence"]

    def _run(self, connected=True, sent=True, replied=True):
        """
        Run one command cycle against a stubbed uplink.

        `replied` models River Song answering: the uplink stamps a timestamp
        when a presence or audio frame arrives, and the manager compares it
        across the wait to tell an answer from a silent server.
        """
        link = MagicMock()
        link.connected = connected
        link.send_utterance = AsyncMock(return_value=sent)
        # last_reply_at is read before and after the wait; advancing it means
        # she answered, leaving it still means nothing came back.
        link.last_reply_at = 100.0
        if replied:
            type(link).last_reply_at = PropertyMock(side_effect=[100.0, 101.0])

        with patch("connectivity.vortex_link.vortex_link", link), \
             patch("audio.audio_manager.REPLY_TIMEOUT_SECONDS", 0.01), \
             patch("core.voice.voice.speak", new_callable=AsyncMock) as speak:
            run(self.manager._capture_and_process_command())
        return link, speak

    def test_a_successful_command_hands_off_and_lets_river_own_the_orb(self):
        """
        The reply arrives asynchronously, so the unit must NOT force IDLE the
        moment the audio is sent — that would blank the orb a fraction of a
        second before River answers.
        """
        self._run()
        self.assertEqual(self._states(), ["LISTENING", "PROCESSING"])

    def test_the_captured_audio_goes_up_the_uplink(self):
        link, _ = self._run()
        link.send_utterance.assert_awaited_once_with(b"pcm")

    def test_no_uplink_returns_to_idle_rather_than_hanging(self):
        self._run(connected=False)
        self.assertEqual(self.manager.state, VortexState.IDLE)
        self.assertEqual(self._states()[-1], "IDLE")

    def test_a_server_that_never_answers_does_not_leave_the_orb_spinning(self):
        """
        Handing over means River owns the orb — and that is a trap if she
        never replies. A wall panel stuck pulsing has no way out.
        """
        self._run(replied=False)
        self.assertEqual(self.manager.state, VortexState.IDLE)

    def test_silence_returns_to_idle_without_reaching_the_network(self):
        self.manager._microphone.stream_until_silence.return_value = []
        link = MagicMock()
        link.connected = True
        link.send_utterance = AsyncMock()
        with patch("connectivity.vortex_link.vortex_link", link):
            run(self.manager._capture_and_process_command())
        link.send_utterance.assert_not_awaited()
        self.assertEqual(self._states(), ["LISTENING", "IDLE"])


class TestOfflineSpeech(unittest.TestCase):
    """A unit that has lost the server must answer with words, not a beep."""

    def setUp(self):
        patcher = patch("audio.audio_manager.ws_hub.broadcast", new_callable=AsyncMock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = make_manager()
        self.manager._microphone.stream_until_silence.return_value = [b"pcm"]

    def _run_failing(self, speak=None):
        """One command cycle with the uplink down — River cannot be reached."""
        link = MagicMock()
        link.connected = False
        link.send_utterance = AsyncMock(return_value=False)
        link.last_reply_at = 0.0
        speak = speak if speak is not None else AsyncMock(return_value=True)
        with patch("connectivity.vortex_link.vortex_link", link), \
             patch("core.voice.voice.speak", speak):
            run(self.manager._capture_and_process_command())
        return speak

    def test_an_unreachable_server_is_explained_out_loud(self):
        from audio.audio_manager import UNREACHABLE_PHRASE
        speak = self._run_failing()
        speak.assert_awaited_once()
        self.assertEqual(speak.await_args.args[0], UNREACHABLE_PHRASE)

    def test_the_apology_does_not_go_back_to_the_server_that_just_failed(self):
        """
        Otherwise the user waits out a connect timeout before hearing an
        apology for a connection that is already known to be down.
        """
        speak = self._run_failing()
        self.assertTrue(speak.await_args.kwargs["prefer_local"])

    def test_a_microphone_failure_is_also_explained(self):
        from audio.audio_manager import MIC_FAILURE_PHRASE
        from audio.microphone import MicrophoneError
        self.manager._microphone.stream_until_silence.side_effect = \
            MicrophoneError("mic gone")
        speak = AsyncMock(return_value=True)
        with patch("core.voice.voice.speak", speak):
            run(self.manager._capture_and_process_command())
        self.assertEqual(speak.await_args.args[0], MIC_FAILURE_PHRASE)

    def test_speech_failing_still_leaves_a_chime(self):
        """The last resort must survive espeak being absent too."""
        self._run_failing(speak=AsyncMock(side_effect=RuntimeError("no espeak")))
        self.manager._speaker.play_chime.assert_any_call("error")

    def test_a_server_that_goes_quiet_says_so_differently(self):
        """
        Accepting the command and then never answering is not the same failure
        as being unreachable — the network is plainly fine, so claiming
        otherwise would be a lie. It admits it does not have an answer.
        """
        from audio.audio_manager import NO_REPLY_PHRASE, UNREACHABLE_PHRASE

        link = MagicMock()
        link.connected = True
        link.send_utterance = AsyncMock(return_value=True)
        link.last_reply_at = 5.0          # never advances: nothing came back
        speak = AsyncMock(return_value=True)

        with patch("connectivity.vortex_link.vortex_link", link), \
             patch("audio.audio_manager.REPLY_TIMEOUT_SECONDS", 0.01), \
             patch("core.voice.voice.speak", speak):
            run(self.manager._capture_and_process_command())

        self.assertEqual(speak.await_args.args[0], NO_REPLY_PHRASE)
        self.assertNotEqual(speak.await_args.args[0], UNREACHABLE_PHRASE)

    def test_a_reply_means_no_apology_at_all(self):
        """River answered; the unit must not talk over her with an excuse."""
        link = MagicMock()
        link.connected = True
        link.send_utterance = AsyncMock(return_value=True)
        type(link).last_reply_at = PropertyMock(side_effect=[10.0, 11.0])
        speak = AsyncMock()

        with patch("connectivity.vortex_link.vortex_link", link), \
             patch("audio.audio_manager.REPLY_TIMEOUT_SECONDS", 0.01), \
             patch("core.voice.voice.speak", speak):
            run(self.manager._capture_and_process_command())

        speak.assert_not_awaited()


class TestVoicePrefersLocal(unittest.TestCase):
    """The prefer_local flag on voice.speak itself."""

    def _voice(self):
        from core.voice import VoiceOutput
        v = VoiceOutput()
        v.set_audio_manager(MagicMock())
        return v

    def test_prefer_local_skips_river_song_entirely(self):
        v = self._voice()
        with patch.object(v, "_tts_from_river_song",
                          new_callable=AsyncMock) as river, \
             patch.object(v, "_tts_local", new_callable=AsyncMock,
                          return_value=b"wav"):
            run(v.speak("hello", prefer_local=True))
        river.assert_not_awaited()

    def test_the_default_still_tries_river_song_first(self):
        v = self._voice()
        with patch.object(v, "_tts_from_river_song", new_callable=AsyncMock,
                          return_value=b"wav") as river:
            run(v.speak("hello"))
        river.assert_awaited_once()

    def test_prefer_local_still_falls_through_to_a_chime(self):
        v = self._voice()
        with patch.object(v, "_tts_local", new_callable=AsyncMock,
                          return_value=None):
            self.assertTrue(run(v.speak("hello", prefer_local=True)))
        v._audio_manager.play_chime.assert_called_once()


if __name__ == "__main__":
    unittest.main()
