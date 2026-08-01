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
from unittest.mock import AsyncMock, MagicMock, patch

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

    def _run_with_response(self, response_audio=b"wav", side_effect=None):
        client = MagicMock()
        client.send_voice_command = AsyncMock(
            return_value=response_audio, side_effect=side_effect)
        with patch("connectivity.api_client.APIClient", return_value=client), \
             patch("core.voice.voice.speak", new_callable=AsyncMock):
            run(self.manager._capture_and_process_command())

    def test_a_successful_command_walks_the_whole_cycle(self):
        self._run_with_response()
        self.assertEqual(
            self._states(),
            ["LISTENING", "PROCESSING", "RESPONDING", "IDLE"],
        )

    def test_the_unit_returns_to_idle_after_answering(self):
        self._run_with_response()
        self.assertEqual(self.manager.state, VortexState.IDLE)

    def test_the_unit_returns_to_idle_when_river_song_fails(self):
        """A stuck 'thinking' orb after a failure would be a visible lie."""
        self._run_with_response(side_effect=RuntimeError("offline"))
        self.assertEqual(self.manager.state, VortexState.IDLE)
        self.assertEqual(self._states()[-1], "IDLE")

    def test_silence_returns_to_idle_without_reaching_the_network(self):
        self.manager._microphone.stream_until_silence.return_value = []
        client = MagicMock()
        client.send_voice_command = AsyncMock()
        with patch("connectivity.api_client.APIClient", return_value=client):
            run(self.manager._capture_and_process_command())
        client.send_voice_command.assert_not_awaited()
        self.assertEqual(self._states(), ["LISTENING", "IDLE"])


class TestOfflineSpeech(unittest.TestCase):
    """A unit that has lost the server must answer with words, not a beep."""

    def setUp(self):
        patcher = patch("audio.audio_manager.ws_hub.broadcast", new_callable=AsyncMock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = make_manager()
        self.manager._microphone.stream_until_silence.return_value = [b"pcm"]

    def _run_failing(self):
        client = MagicMock()
        client.send_voice_command = AsyncMock(side_effect=RuntimeError("offline"))
        speak = AsyncMock(return_value=True)
        with patch("connectivity.api_client.APIClient", return_value=client), \
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
        client = MagicMock()
        client.send_voice_command = AsyncMock(side_effect=RuntimeError("offline"))
        with patch("connectivity.api_client.APIClient", return_value=client), \
             patch("core.voice.voice.speak",
                   AsyncMock(side_effect=RuntimeError("no espeak"))):
            run(self.manager._capture_and_process_command())
        self.manager._speaker.play_chime.assert_any_call("error")

    def test_a_silent_success_chimes_rather_than_apologising(self):
        """
        River Song answering with no audio is not a failure — it heard us.
        Saying 'I can't reach River Song' there would be a lie.
        """
        client = MagicMock()
        client.send_voice_command = AsyncMock(return_value=None)
        speak = AsyncMock()
        with patch("connectivity.api_client.APIClient", return_value=client), \
             patch("core.voice.voice.speak", speak):
            run(self.manager._capture_and_process_command())
        speak.assert_not_awaited()
        self.manager._speaker.play_chime.assert_any_call("done")


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
