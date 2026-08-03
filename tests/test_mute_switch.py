"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_mute_switch.py
Purpose:     Tests for the physical microphone mute switch.

             The property under test is not "does the flag flip". It is that
             a switch you can see cannot be overridden by software, and that
             muted actually means no audio is captured — because before this,
             PrivacyManager.mute_microphone() set a flag, lit an LED, and
             blocked nothing at all.

             A privacy control that reports "muted" while audio keeps flowing
             is worse than having none, because it is believed.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def run(coro):
    """Run a coroutine on the suite's shared event loop."""
    return asyncio.get_event_loop().run_until_complete(coro)


def make_privacy(switch_muted=None, on_change=None):
    """
    A PrivacyManager with GPIO faked.

    switch_muted: None means no switch fitted; True/False sets its position.
    """
    from safety.privacy_manager import PrivacyManager

    with patch("safety.privacy_manager.config") as cfg:
        cfg.get.side_effect = lambda k, d=None: d
        manager = PrivacyManager(on_change=on_change)

    if switch_muted is not None:
        gpio = MagicMock()
        # Pulled up: LOW (0) means the switch is closed to ground = muted.
        gpio.input.return_value = 0 if switch_muted else 1
        manager._gpio = gpio
        manager._gpio_available = True
        manager._read_switch()
    return manager


class TestSwitchIsAuthoritative(unittest.TestCase):
    """Software can make things more private. It cannot make them less."""

    def test_the_switch_mutes_regardless_of_the_software_flag(self):
        manager = make_privacy(switch_muted=True)
        self.assertFalse(manager._mic_muted)   # software says live
        self.assertTrue(manager.mic_muted)     # the switch says otherwise

    def test_software_cannot_unmute_while_the_switch_is_on(self):
        """
        The whole reason the switch exists. A setting you can toggle in an app
        is a preference; a switch you can see is a promise, and a promise
        software can quietly revoke is not one.
        """
        manager = make_privacy(switch_muted=True)
        self.assertFalse(manager.unmute_microphone())
        self.assertTrue(manager.mic_muted)

    def test_software_can_still_mute_on_top_of_an_open_switch(self):
        manager = make_privacy(switch_muted=False)
        manager.mute_microphone()
        self.assertTrue(manager.mic_muted)

    def test_software_unmute_works_when_the_switch_is_open(self):
        manager = make_privacy(switch_muted=False)
        manager.mute_microphone()
        self.assertTrue(manager.unmute_microphone())
        self.assertFalse(manager.mic_muted)

    def test_a_unit_with_no_switch_behaves_as_before(self):
        manager = make_privacy(switch_muted=None)
        self.assertFalse(manager.switch_fitted)
        manager.mute_microphone()
        self.assertTrue(manager.mic_muted)
        self.assertTrue(manager.unmute_microphone())

    def test_the_led_follows_the_switch_not_the_flag(self):
        manager = make_privacy(switch_muted=True)
        manager._apply_mic_state()
        # Last call is the mic LED pin being driven with the effective state.
        pin, value = manager._gpio.output.call_args.args
        self.assertTrue(value)


class TestSwitchMovement(unittest.TestCase):
    """Flipping it has to take effect now, and tell the screen."""

    def test_moving_the_switch_is_noticed_and_announced(self):
        notified = []

        async def on_change(state):
            notified.append(state)

        manager = make_privacy(switch_muted=False, on_change=on_change)
        manager._gpio.input.return_value = 0          # flipped to muted

        async def one_poll():
            task = asyncio.create_task(manager._watch_switch())
            await asyncio.sleep(0.05)
            task.cancel()

        with patch("safety.privacy_manager.PRIVACY_SWITCH_POLL_SECONDS", 0.01):
            run(one_poll())

        self.assertTrue(manager.switch_muted)
        self.assertTrue(notified and notified[-1]["mic_muted"])
        self.assertTrue(notified[-1]["mic_switch_muted"])

    def test_state_reports_both_fitted_and_position(self):
        """
        The screen needs both: a unit with no switch must not imply it has
        one, and a unit whose switch is on shows the toggle locked rather than
        as something the user failed to turn off.
        """
        fitted = make_privacy(switch_muted=False).get_state()
        self.assertTrue(fitted["mic_switch_fitted"])
        self.assertFalse(fitted["mic_switch_muted"])

        absent = make_privacy(switch_muted=None).get_state()
        self.assertFalse(absent["mic_switch_fitted"])


class TestMuteActuallyBlocksAudio(unittest.TestCase):
    """
    The bug this was built on top of: PrivacyManager's mute reached nothing.

    Microphone kept its own separate flag that only AudioManager touched, so
    the privacy control lit an LED and blocked no audio whatsoever.
    """

    def _mic(self, privacy=None):
        from audio.microphone import Microphone
        with patch("audio.microphone.config") as cfg:
            cfg.get.side_effect = lambda k, d=None: d
            mic = Microphone()
        mic._stream = MagicMock()
        mic._stream.read.return_value = b"\x01\x02" * 256
        if privacy:
            mic.set_privacy_manager(privacy)
        return mic

    def test_the_privacy_manager_mute_reaches_the_microphone(self):
        privacy = make_privacy(switch_muted=False)
        mic = self._mic(privacy)
        self.assertFalse(mic.muted)
        privacy.mute_microphone()
        self.assertTrue(mic.muted)

    def test_a_muted_microphone_returns_silence_not_audio(self):
        privacy = make_privacy(switch_muted=True)
        mic = self._mic(privacy)
        frame = mic.read_frame()
        self.assertEqual(set(frame), {0}, "muted mic returned real audio")

    def test_command_capture_is_refused_while_muted(self):
        """
        This path read the hardware stream directly and never checked mute,
        so a muted microphone would still have captured a command and sent it
        upstream. Nothing at all should come out of it.
        """
        privacy = make_privacy(switch_muted=True)
        mic = self._mic(privacy)
        self.assertEqual(list(mic.stream_until_silence()), [])
        mic._stream.read.assert_not_called()

    def test_muting_mid_capture_stops_the_rest_of_the_sentence(self):
        privacy = make_privacy(switch_muted=False)
        mic = self._mic(privacy)

        chunks = []
        gen = mic.stream_until_silence(max_duration=5)
        chunks.append(next(gen))       # one real chunk
        privacy.mute_microphone()      # hit mute mid-sentence
        chunks.extend(gen)             # generator must stop

        self.assertEqual(len(chunks), 1)


class TestWakeWordRespectsMute(unittest.TestCase):
    """
    The detector opens its OWN audio stream, separate from the Microphone.

    Without an explicit check, a muted unit would still wake to its name —
    which is not what anyone means by muted.
    """

    def _detector(self, privacy):
        from audio.wake_word import WakeWordDetector
        settings = {"wake_word": "hey jarvis", "wake_word_threshold": 0.5,
                    "wake_word_model_dir": "audio/models"}
        with patch("audio.wake_word.config") as cfg:
            cfg.get.side_effect = lambda k, d=None: settings.get(k, d)
            return WakeWordDetector(on_wake_word=MagicMock(),
                                    privacy_manager=privacy)

    def test_a_muted_unit_reports_itself_muted_to_the_detector(self):
        self.assertTrue(self._detector(make_privacy(switch_muted=True))._is_muted())

    def test_an_unmuted_unit_does_not(self):
        self.assertFalse(self._detector(make_privacy(switch_muted=False))._is_muted())

    def test_no_privacy_manager_means_not_muted(self):
        self.assertFalse(self._detector(None)._is_muted())

    def test_a_broken_privacy_manager_fails_towards_listening(self):
        """
        Deliberate: a crash should not silently deafen a unit with no way for
        the user to tell why. The LED and settings screen still report truth.
        """
        broken = MagicMock()
        type(broken).mic_muted = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("gpio gone")))
        self.assertFalse(self._detector(broken)._is_muted())


class TestSettingsApiReportsTheSwitch(unittest.TestCase):
    """What the screen is told."""

    def _client(self, switch_muted):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core import settings_api

        privacy = make_privacy(switch_muted=switch_muted)
        settings_api.set_subsystems(privacy_manager=privacy)
        self.addCleanup(lambda: setattr(settings_api, "_privacy_manager", None))

        patcher = patch("core.settings_api.config")
        cfg = patcher.start()
        self.addCleanup(patcher.stop)
        cfg.get.side_effect = lambda k, d=None: d

        app = FastAPI()
        app.include_router(settings_api.router)
        return TestClient(app), privacy

    def test_the_switch_position_is_reported(self):
        client, _ = self._client(switch_muted=True)
        body = client.get("/api/vortex/v1/settings").json()
        self.assertTrue(body["mic_switch_fitted"])
        self.assertTrue(body["mic_switch_muted"])
        self.assertTrue(body["mic_muted"])

    def test_unmuting_against_the_switch_is_refused_not_faked(self):
        """
        Silently reporting an unmute that did not happen is exactly the lie
        the switch exists to make impossible.
        """
        client, privacy = self._client(switch_muted=True)
        resp = client.post("/api/vortex/v1/settings", json={"mic_muted": False})
        self.assertEqual(resp.status_code, 409)
        self.assertIn("switch", str(resp.json()["detail"]).lower())
        self.assertTrue(privacy.mic_muted)

    def test_a_unit_with_no_switch_says_so(self):
        client, _ = self._client(switch_muted=None)
        body = client.get("/api/vortex/v1/settings").json()
        self.assertFalse(body["mic_switch_fitted"])
        self.assertFalse(body["capabilities"]["mic_switch"])


if __name__ == "__main__":
    unittest.main()
