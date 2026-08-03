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

#: Builds that ship a runnable profile. The remaining sheets are documented
#: alternatives that deliberately do not run this software.
BUILDS = ["hub-7-counter", "hub-10-wall", "round-spot", "mini-screenless"]

#: Documented, but cannot run this software, so they ship no profile.
NON_VORTEX = ["satellite-echo-show", "micimike-nest-mini"]


def sheets():
    """Every build sheet in the folder, by name."""
    return sorted(p.stem for p in HARDWARE.glob("*.md") if p.stem != "README")


def load(build):
    return json.loads((HARDWARE / f"{build}.json").read_text())


class TestFolderShape(unittest.TestCase):
    """
    One folder, one file per build. Flat on purpose — a directory per build
    buys nothing and buries the thing you actually want to read.
    """

    def test_the_folder_stays_flat(self):
        subdirs = [p.name for p in HARDWARE.iterdir() if p.is_dir()]
        self.assertEqual(subdirs, [], f"hardware/ must stay flat, found {subdirs}")

    def test_every_sheet_is_accounted_for(self):
        """A sheet in neither list is a build nothing is checking."""
        self.assertEqual(sheets(), sorted(BUILDS + NON_VORTEX))

    def test_the_index_links_every_build(self):
        index = (HARDWARE / "README.md").read_text()
        for build in sheets():
            self.assertIn(f"({build}.md)", index,
                          f"{build} is not linked from the index")

    def test_every_runnable_build_ships_a_profile(self):
        for build in BUILDS:
            self.assertTrue((HARDWARE / f"{build}.json").exists(),
                            f"{build} has no profile")

    def test_builds_that_cannot_run_vortex_ship_no_profile(self):
        """
        A profile beside those sheets would invite someone to copy it onto
        hardware that will never boot this software.
        """
        for build in NON_VORTEX:
            self.assertFalse((HARDWARE / f"{build}.json").exists(),
                             f"{build} must not ship a profile")

    def test_no_orphan_profiles(self):
        """A profile with no build sheet is a profile nobody can follow."""
        for profile in HARDWARE.glob("*.json"):
            self.assertTrue((HARDWARE / f"{profile.stem}.md").exists(),
                            f"{profile.name} has no build sheet")


class TestProfilesLoad(unittest.TestCase):
    """The profiles have to actually work, not just parse."""

    def test_every_profile_is_valid_json(self):
        for build in BUILDS:
            load(build)   # raises if not

    def test_every_profile_loads_through_the_real_config(self):
        from core.config import Config
        for build in BUILDS:
            cfg = Config()
            cfg.load(profile_path=str(HARDWARE / f"{build}.json"))
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
        cfg.load(profile_path=str(HARDWARE / f"{build}.json"))
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
        expected = {"hub-7-counter": (800, 480), "hub-10-wall": (1280, 800),
                    "round-spot": (720, 720)}
        for build, (width, height) in expected.items():
            cfg = self._config(build)
            self.assertEqual((cfg.get("screen_width"), cfg.get("screen_height")),
                             (width, height), build)

    def test_every_build_declares_its_screen_shape(self):
        """
        A round panel that does not say so renders a rectangular layout and
        loses every corner behind the bezel — broken in a way that is hard to
        diagnose from a photo. Explicit on every build, never defaulted.
        """
        for build in BUILDS:
            shape = self._config(build).get("screen_shape")
            self.assertIn(shape, {"rectangular", "round", "none"},
                          f"{build} declares no screen shape")

    def test_a_round_panel_is_square(self):
        """A circular screen whose width and height differ is a typo."""
        for build in BUILDS:
            cfg = self._config(build)
            if cfg.get("screen_shape") == "round":
                self.assertEqual(cfg.get("screen_width"), cfg.get("screen_height"),
                                 f"{build} is round but not square")

    def test_a_screenless_build_claims_no_shape(self):
        self.assertEqual(self._config("mini-screenless").get("screen_shape"), "none")

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
