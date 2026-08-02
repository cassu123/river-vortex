"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_settings_api.py
Purpose:     Tests for core/settings_api.py — this box's own settings.

             The properties that matter here are not "does the slider move".
             They are: these settings belong to the DEVICE and not to a
             person, they work with River Song unreachable, and a control the
             unit does not have says so rather than pretending.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import settings_api

URL = "/api/vortex/v1/settings"


class SettingsTestCase(unittest.TestCase):
    """Base — a client with whichever subsystems the test wants present."""

    def _client(self, audio=True, screen=True, privacy=True, wake=True,
                camera_fitted=False, uplink=False):
        self.audio = MagicMock() if audio else None
        self.screen = MagicMock() if screen else None
        self.privacy = MagicMock() if privacy else None
        self.wake = MagicMock() if wake else None

        if self.screen:
            self.screen.get_brightness.return_value = 80
        if self.privacy:
            self.privacy.get_state.return_value = {
                "mic_muted": False, "cam_muted": False, "cam_active": False,
            }
        if self.wake:
            self.wake.threshold = 0.5
            self.wake.set_threshold.return_value = True

        settings_api.set_subsystems(
            audio_manager=self.audio, screen_manager=self.screen,
            privacy_manager=self.privacy, wake_word=self.wake,
        )
        # set_subsystems only overwrites non-None, so clear explicitly.
        for name, value in (("_audio_manager", self.audio),
                            ("_screen_manager", self.screen),
                            ("_privacy_manager", self.privacy),
                            ("_wake_word", self.wake)):
            setattr(settings_api, name, value)
        self.addCleanup(lambda: [setattr(settings_api, n, None) for n in
                                 ("_audio_manager", "_screen_manager",
                                  "_privacy_manager", "_wake_word")])

        camera = MagicMock()
        camera.fitted = camera_fitted
        link = MagicMock()
        link.connected = uplink
        patch.dict("sys.modules", {}).start()
        self._camera_patch = patch("display.camera.camera", camera)
        self._camera_patch.start()
        self.addCleanup(self._camera_patch.stop)
        self._link_patch = patch("connectivity.vortex_link.vortex_link", link)
        self._link_patch.start()
        self.addCleanup(self._link_patch.stop)

        cfg = {"volume": 70, "unit_id": "vortex-1", "unit_name": "Kitchen",
               "location": "Kitchen", "wake_word": "hey jarvis"}
        patcher = patch("core.settings_api.config")
        mock_cfg = patcher.start()
        self.addCleanup(patcher.stop)
        mock_cfg.get.side_effect = lambda k, d=None: cfg.get(k, d)
        self.saved = mock_cfg.save_profile

        app = FastAPI()
        app.include_router(settings_api.router)
        return TestClient(app)


class TestReading(SettingsTestCase):
    """What the screen needs to draw itself."""

    def test_settings_come_back_with_the_current_values(self):
        client = self._client()
        body = client.get(URL).json()
        self.assertEqual(body["volume"], 70)
        self.assertEqual(body["brightness"], 80)
        self.assertEqual(body["wake_word_threshold"], 0.5)
        self.assertFalse(body["mic_muted"])

    def test_capabilities_say_what_this_unit_can_offer(self):
        """
        So the screen never draws a brightness slider on a unit with no
        backlight, or a camera toggle on a unit with no camera.
        """
        body = self._client(screen=False, camera_fitted=False).get(URL).json()
        can = body["capabilities"]
        self.assertFalse(can["brightness"])
        self.assertFalse(can["camera"])
        self.assertTrue(can["volume"])

    def test_a_fitted_camera_offers_its_mute(self):
        body = self._client(camera_fitted=True).get(URL).json()
        self.assertTrue(body["capabilities"]["camera"])

    def test_the_uplink_state_is_reported(self):
        """Most of why anyone opens this screen: is it talking to the server."""
        self.assertTrue(self._client(uplink=True).get(URL).json()["uplink_connected"])
        self.assertFalse(self._client(uplink=False).get(URL).json()["uplink_connected"])

    def test_identity_is_reported_so_you_know_which_unit_you_are_at(self):
        body = self._client().get(URL).json()
        self.assertEqual(body["unit_id"], "vortex-1")
        self.assertEqual(body["unit_name"], "Kitchen")

    def test_nothing_here_is_scoped_to_a_user(self):
        """
        These are the box's settings, not a person's. A user field creeping in
        would be the start of per-account state on a device that has no
        accounts and must work when the server is unreachable.
        """
        body = self._client().get(URL).json()
        for key in body:
            self.assertNotIn("user", key.lower())


class TestWriting(SettingsTestCase):
    """Applying a change."""

    def test_volume_reaches_the_audio_manager_and_is_persisted(self):
        client = self._client()
        resp = client.post(URL, json={"volume": 40})
        self.assertEqual(resp.status_code, 200)
        self.audio.set_volume.assert_called_once_with(40)
        self.saved.assert_called_once()
        self.assertEqual(self.saved.call_args.args[0]["volume"], 40)

    def test_brightness_reaches_the_screen_manager(self):
        client = self._client()
        client.post(URL, json={"brightness": 30})
        self.screen.set_brightness.assert_called_once_with(30)

    def test_the_wake_threshold_reaches_the_detector(self):
        client = self._client()
        client.post(URL, json={"wake_word_threshold": 0.8})
        self.wake.set_threshold.assert_called_once_with(0.8)

    def test_muting_the_microphone_calls_the_privacy_manager(self):
        client = self._client()
        client.post(URL, json={"mic_muted": True})
        self.privacy.mute_microphone.assert_called_once()

    def test_a_mic_mute_is_deliberately_not_persisted(self):
        """
        A microphone that silently comes back muted after a power cut is a
        unit that looks broken. Coming back live is at least honest, and the
        LED says which it is.
        """
        client = self._client()
        client.post(URL, json={"mic_muted": True})
        self.saved.assert_not_called()

    def test_only_the_fields_sent_are_touched(self):
        """Two people adjusting different things must not overwrite each other."""
        client = self._client()
        client.post(URL, json={"volume": 20})
        self.screen.set_brightness.assert_not_called()
        self.wake.set_threshold.assert_not_called()

    def test_a_control_the_unit_lacks_is_refused_not_ignored(self):
        """A slider that appears to do nothing is worse than one that says why."""
        client = self._client(screen=False)
        resp = client.post(URL, json={"brightness": 50})
        self.assertEqual(resp.status_code, 409)
        self.assertIn("brightness", str(resp.json()["detail"]))

    def test_a_partial_refusal_still_applies_the_rest(self):
        client = self._client(screen=False)
        resp = client.post(URL, json={"volume": 30, "brightness": 50})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["applied"]["volume"], 30)
        self.assertIn("brightness", resp.json()["refused"])

    def test_out_of_range_values_are_rejected_at_the_seam(self):
        client = self._client()
        for payload in ({"volume": 150}, {"volume": -1},
                        {"brightness": 101}, {"wake_word_threshold": 5}):
            self.assertEqual(client.post(URL, json=payload).status_code, 422)

    def test_a_failed_save_does_not_undo_a_live_change(self):
        """The volume is already down; failing to write it is worth a log, not a revert."""
        client = self._client()
        self.saved.side_effect = OSError("read-only filesystem")
        resp = client.post(URL, json={"volume": 25})
        self.assertEqual(resp.status_code, 200)
        self.audio.set_volume.assert_called_once_with(25)


class TestOfflineOperation(SettingsTestCase):
    """The whole reason this lives on the device."""

    def test_settings_work_with_river_song_unreachable(self):
        """
        Nothing here calls out. If it did, the one moment you most want to
        mute a microphone — the network is down and the app cannot reach you —
        is the moment it would stop working.
        """
        client = self._client(uplink=False)
        self.assertEqual(client.get(URL).status_code, 200)
        self.assertEqual(client.post(URL, json={"volume": 10}).status_code, 200)
        self.audio.set_volume.assert_called_once_with(10)


if __name__ == "__main__":
    unittest.main()
