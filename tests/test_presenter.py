"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_presenter.py
Purpose:     Tests for core/presenter.py and core/voice.py — the layer that
             decides whether an event is shown, spoken, or both.

             The behaviour under test is what makes one image work on both a
             screened Hub and a screenless Mini, so these tests assert the
             screenless path explicitly rather than assuming a display.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.presenter import (
    Presenter,
    describe_duration,
    routine_step_phrase,
    timer_done_phrase,
)


def run(coro):
    """
    Run a coroutine to completion on the suite's shared event loop.

    Deliberately NOT asyncio.run(): that closes the loop and clears the
    thread's current loop on exit, which breaks every other test module in
    this suite, since they all reach for asyncio.get_event_loop().
    """
    return asyncio.get_event_loop().run_until_complete(coro)


class TestFormFactorDetection(unittest.TestCase):
    """A unit must know whether it has a screen before it can route output."""

    def _presenter_with(self, settings):
        p = Presenter()
        patcher = patch("core.presenter.config")
        mock_config = patcher.start()
        self.addCleanup(patcher.stop)
        mock_config.get.side_effect = lambda key, default=None: settings.get(key, default)
        return p

    def test_mini_form_factor_has_no_screen(self):
        p = self._presenter_with({"form_factor": "mini"})
        self.assertFalse(p.has_screen)

    def test_hub_form_factor_has_screen(self):
        p = self._presenter_with({"form_factor": "hub"})
        self.assertTrue(p.has_screen)

    def test_hub_max_form_factor_has_screen(self):
        p = self._presenter_with({"form_factor": "hub_max"})
        self.assertTrue(p.has_screen)

    def test_falls_back_to_capability_flag_when_form_factor_unset(self):
        """Older profiles have no form_factor — capabilities.display decides."""
        p = self._presenter_with({"form_factor": "", "cap_display": False})
        self.assertFalse(p.has_screen)

    def test_defaults_to_having_a_screen(self):
        """Absent any signal, assume a screen rather than talking constantly."""
        p = self._presenter_with({})
        self.assertTrue(p.has_screen)


class TestPresentRouting(unittest.TestCase):
    """Where an event actually goes, per form factor."""

    def setUp(self):
        # Stop each patcher individually. patch.stopall() would also tear down
        # patches started by other test modules' setUp, breaking them.
        ws_patcher = patch("core.presenter.ws_hub.broadcast", new_callable=AsyncMock)
        voice_patcher = patch("core.presenter.voice.speak", new_callable=AsyncMock)
        self.ws = ws_patcher.start()
        self.voice = voice_patcher.start()
        self.addCleanup(ws_patcher.stop)
        self.addCleanup(voice_patcher.stop)

    def _presenter(self, has_screen):
        p = Presenter()
        p._has_screen = has_screen
        return p

    def test_screen_always_receives_the_event(self):
        """The broadcast is unconditional — a Mini may still have a browser open."""
        run(self._presenter(False).present({"type": "x"}, speech="hello"))
        self.ws.assert_awaited_once()

    def test_mini_speaks_events_that_carry_a_phrase(self):
        run(self._presenter(False).present({"type": "x"}, speech="hello"))
        self.voice.assert_awaited_once()
        self.assertEqual(self.voice.await_args.args[0], "hello")

    def test_screened_unit_stays_quiet_by_default(self):
        """Otherwise a kitchen Hub would narrate every state change."""
        run(self._presenter(True).present({"type": "x"}, speech="hello"))
        self.voice.assert_not_awaited()

    def test_screened_unit_speaks_when_told_to(self):
        """Timers and announcements must be heard, not just drawn."""
        run(self._presenter(True).present(
            {"type": "x"}, speech="hello", speak_on_screen=True))
        self.voice.assert_awaited_once()

    def test_events_without_a_phrase_are_never_spoken(self):
        """A list refresh is visual-only on every form factor."""
        run(self._presenter(False).present({"type": "lists_update"}))
        self.voice.assert_not_awaited()

    def test_speech_still_happens_when_the_broadcast_fails(self):
        """A screenless unit must not go silent because the socket died."""
        self.ws.side_effect = RuntimeError("no clients")
        run(self._presenter(False).present({"type": "x"}, speech="hello"))
        self.voice.assert_awaited_once()

    def test_broadcast_still_happens_when_speech_fails(self):
        """A broken speaker must not blank the screen."""
        self.voice.side_effect = RuntimeError("no audio device")
        run(self._presenter(True).present(
            {"type": "x"}, speech="hello", speak_on_screen=True))
        self.ws.assert_awaited_once()


class TestPhrases(unittest.TestCase):
    """What River actually says. These are user-facing strings."""

    def test_duration_uses_natural_units(self):
        self.assertEqual(describe_duration(480), "8 minutes")
        self.assertEqual(describe_duration(60), "1 minute")
        self.assertEqual(describe_duration(5400), "1 hour 30 minutes")
        self.assertEqual(describe_duration(45), "45 seconds")

    def test_labelled_timer_uses_its_label(self):
        phrase = timer_done_phrase({"label": "pasta", "duration_seconds": 480})
        self.assertIn("pasta", phrase)

    def test_unlabelled_timer_falls_back_to_duration(self):
        phrase = timer_done_phrase({"label": "", "duration_seconds": 480})
        self.assertIn("8 minutes", phrase)

    def test_timer_with_nothing_useful_still_says_something(self):
        self.assertTrue(timer_done_phrase({}))

    def test_routine_step_includes_position_and_text(self):
        phrase = routine_step_phrase({
            "active": True,
            "step": {"text": "Brown the onions."},
            "step_index": 2,
            "step_count": 6,
        })
        self.assertIn("Step 3 of 6", phrase)
        self.assertIn("Brown the onions.", phrase)

    def test_inactive_routine_says_nothing(self):
        self.assertIsNone(routine_step_phrase({"active": False}))

    def test_routine_without_a_step_says_nothing(self):
        self.assertIsNone(routine_step_phrase({"active": True, "step": None}))


class TestVoiceFallback(unittest.TestCase):
    """Speech must survive River Song being unreachable."""

    def test_falls_back_to_espeak_when_river_song_is_down(self):
        from core.voice import VoiceOutput

        audio = MagicMock()
        v = VoiceOutput(audio_manager=audio)
        with patch.object(v, "_tts_from_river_song", new_callable=AsyncMock) as remote, \
             patch.object(v, "_tts_local", new_callable=AsyncMock) as local:
            remote.return_value = None
            local.return_value = b"RIFFfake"
            self.assertTrue(run(v.speak("timer done")))
        audio.speaker.play.assert_called_once()

    def test_chimes_when_no_speech_engine_is_available_at_all(self):
        from core.voice import VoiceOutput

        audio = MagicMock()
        v = VoiceOutput(audio_manager=audio)
        with patch.object(v, "_tts_from_river_song", new_callable=AsyncMock) as remote, \
             patch.object(v, "_tts_local", new_callable=AsyncMock) as local:
            remote.return_value = None
            local.return_value = None
            self.assertTrue(run(v.speak("timer done")))
        audio.play_chime.assert_called_once()

    def test_silent_unit_reports_failure_rather_than_raising(self):
        from core.voice import VoiceOutput

        v = VoiceOutput(audio_manager=None)
        self.assertFalse(run(v.speak("nobody can hear this")))

    def test_empty_text_is_ignored(self):
        from core.voice import VoiceOutput

        audio = MagicMock()
        v = VoiceOutput(audio_manager=audio)
        self.assertFalse(run(v.speak("   ")))
        audio.speaker.play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
