"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_hardware_profiles.py
Purpose:     Tests for the build profiles under hardware/.

             Those profiles are not documentation — the software reads them at
             boot and they decide what a unit does. A build sheet whose profile
             does not load, or whose capabilities do not match the parts list
             above it, is a build sheet that lies to whoever follows it.
Author:      [Author Placeholder]
Version:     1.0.0
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import json
import pathlib
import unittest
from unittest.mock import patch

HARDWARE = pathlib.Path("hardware")

#: Builds that ship a runnable profile. The other folders are documented
#: alternatives that deliberately do not run this software.
BUILDS = ["hub-7-counter", "hub-10-wall", "mini-screenless"]


def load(build):
    return json.loads((HARDWARE / build / "vortex_profile.json").read_text())


class TestEveryBuildIsDocumented(unittest.TestCase):
    """Each folder explains itself, and the index lists it."""

    def test_every_build_folder_has_a_readme(self):
        for folder in HARDWARE.iterdir():
            if folder.is_dir():
                self.assertTrue((folder / "README.md").exists(),
                                f"{folder.name} has no README")

    def test_the_index_links_every_build(self):
        index = (HARDWARE / "README.md").read_text()
        for folder in HARDWARE.iterdir():
            if folder.is_dir():
                self.assertIn(folder.name, index,
                              f"{folder.name} is not in the index")

    def test_builds_that_cannot_run_vortex_ship_no_profile(self):
        """
        A profile in those folders would invite someone to copy it onto a unit
        that cannot run this software at all.
        """
        for name in ("satellite-echo-show", "micimike-nest-mini"):
            self.assertFalse((HARDWARE / name / "vortex_profile.json").exists(),
                             f"{name} must not ship a profile")


class TestProfilesLoad(unittest.TestCase):
    """The profiles have to actually work, not just parse."""

    def test_every_profile_is_valid_json(self):
        for build in BUILDS:
            load(build)   # raises if not

    def test_every_profile_loads_through_the_real_config(self):
        from core.config import Config
        for build in BUILDS:
            cfg = Config()
            cfg.load(profile_path=str(HARDWARE / build / "vortex_profile.json"))
            self.assertTrue(cfg.get("unit_id"), f"{build} produced no unit id")

    def test_no_build_ships_an_identity(self):
        """
        A unit flashed from an image must not claim a room it was never
        installed in, and units from one image must not share an id.
        """
        for build in BUILDS:
            data = load(build)
            self.assertFalse(data.get("configured"), build)
            for key in ("unit_id", "unit_name", "location"):
                self.assertNotIn(key, data, f"{build} bakes in {key}")

    def test_every_camera_purpose_ships_off(self):
        for build in BUILDS:
            for purpose, enabled in load(build)["camera_purposes"].items():
                self.assertFalse(enabled, f"{build}: {purpose} ships enabled")


class TestProfilesMatchTheirBuild(unittest.TestCase):
    """The profile has to describe the parts list above it."""

    def _config(self, build):
        from core.config import Config
        cfg = Config()
        cfg.load(profile_path=str(HARDWARE / build / "vortex_profile.json"))
        return cfg

    def test_the_mini_declares_no_screen(self):
        """
        This is the value that makes the presenter SPEAK events rather than
        show them. Get it wrong and a screenless unit is silently useless.
        """
        cfg = self._config("mini-screenless")
        self.assertEqual(cfg.get("form_factor"), "mini")
        self.assertFalse(cfg.get("cap_display"))

    def test_the_mini_really_is_treated_as_screenless(self):
        """Assert the behaviour, not just the flag."""
        from core.presenter import Presenter
        cfg = self._config("mini-screenless")
        presenter = Presenter()
        with patch("core.presenter.config", cfg):
            self.assertFalse(presenter.has_screen)

    def test_screened_builds_are_treated_as_screened(self):
        from core.presenter import Presenter
        for build in ("hub-7-counter", "hub-10-wall"):
            cfg = self._config(build)
            presenter = Presenter()
            with patch("core.presenter.config", cfg):
                self.assertTrue(presenter.has_screen, build)

    def test_screen_dimensions_match_the_declared_panel(self):
        expected = {"hub-7-counter": (800, 480), "hub-10-wall": (1280, 800)}
        for build, (width, height) in expected.items():
            cfg = self._config(build)
            self.assertEqual((cfg.get("screen_width"), cfg.get("screen_height")),
                             (width, height), build)

    def test_no_build_ships_with_a_camera_it_does_not_have(self):
        """Optional hardware defaults absent — assuming one is a privacy bug."""
        for build in BUILDS:
            self.assertFalse(self._config(build).get("cap_camera"), build)

    def test_every_wake_word_has_a_model_that_could_exist(self):
        """
        A profile naming a wake word with no matching model is a unit that
        never wakes. Stock openWakeWord phrases only.
        """
        from audio.wake_word import model_name_for
        stock = {"alexa", "hey_mycroft", "hey_jarvis", "hey_rhasspy"}
        for build in BUILDS:
            name = model_name_for(self._config(build).get("wake_word"))
            self.assertIn(name, stock,
                          f"{build} wants '{name}', which is not a stock model")


if __name__ == "__main__":
    unittest.main()
