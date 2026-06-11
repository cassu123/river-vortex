"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_setup.py
Purpose:     Unit tests for first-run pairing — PairingSession, Config's
             `configured` flag and save_profile() persistence, the
             /api/vortex/v1/setup/* API, and discovery helper functions.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-06-11
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import json
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────────────────────────────────────
# PairingSession
# ─────────────────────────────────────────────────────────────────────────────

class TestPairingSession(unittest.TestCase):
    """Tests for core/pairing.py — PairingSession."""

    def _make_session(self):
        from core.pairing import PairingSession
        return PairingSession()

    def test_no_pin_before_generate(self):
        """A new session has no PIN until generate() is called."""
        session = self._make_session()
        self.assertIsNone(session.pin)
        self.assertFalse(session.verify("123456"))

    def test_generate_returns_six_digit_numeric_pin(self):
        """generate() returns a 6-digit numeric string and stores it."""
        from core.constants import PAIRING_PIN_LENGTH
        session = self._make_session()
        pin = session.generate()
        self.assertEqual(len(pin), PAIRING_PIN_LENGTH)
        self.assertTrue(pin.isdigit())
        self.assertEqual(session.pin, pin)

    def test_verify_accepts_correct_pin(self):
        """verify() returns True for the PIN that was generated."""
        session = self._make_session()
        pin = session.generate()
        self.assertTrue(session.verify(pin))

    def test_verify_rejects_incorrect_pin(self):
        """verify() returns False for any non-matching PIN."""
        session = self._make_session()
        session.generate()
        self.assertFalse(session.verify("000000"))

    def test_clear_invalidates_pin(self):
        """clear() removes the PIN so verify() always fails afterward."""
        session = self._make_session()
        pin = session.generate()
        session.clear()
        self.assertIsNone(session.pin)
        self.assertFalse(session.verify(pin))


# ─────────────────────────────────────────────────────────────────────────────
# Config — `configured` flag and save_profile()
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigPairingPersistence(unittest.TestCase):
    """Tests for core/config.py — `configured` derivation and save_profile()."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.profile_path = Path(self.tmpdir.name) / "vortex_profile.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_config(self):
        from core.config import Config
        cfg = Config()
        cfg.load(profile_path=str(self.profile_path))
        return cfg

    def test_unconfigured_when_no_profile_and_no_api_key(self):
        """A fresh unit with no profile file is unconfigured by default."""
        cfg = self._make_config()
        self.assertFalse(cfg.get("configured"))

    def test_save_profile_persists_pairing_and_marks_configured(self):
        """save_profile() writes pairing data to disk and flips `configured`."""
        cfg = self._make_config()
        cfg.save_profile({
            "configured": True,
            "river_song_api_url": "http://riversong.local",
            "river_song_api_key": "test-key-123",
            "unit_name": "Office Vortex",
            "location": "Office",
        })

        self.assertTrue(cfg.get("configured"))
        self.assertEqual(cfg.get("river_song_api_key"), "test-key-123")
        self.assertEqual(cfg.get("unit_name"), "Office Vortex")

        with self.profile_path.open(encoding="utf-8") as fh:
            on_disk = json.load(fh)
        self.assertTrue(on_disk["configured"])
        self.assertEqual(on_disk["river_song_api_key"], "test-key-123")

        # A fresh Config loading the same profile should also be configured.
        cfg2 = self._make_config()
        self.assertTrue(cfg2.get("configured"))
        self.assertEqual(cfg2.get("unit_name"), "Office Vortex")

    def test_save_profile_preserves_unrelated_existing_keys(self):
        """save_profile() merges into the existing file rather than replacing it."""
        cfg = self._make_config()
        cfg.save_profile({"location": "Garage"})
        cfg.save_profile({"unit_name": "Garage Vortex"})

        with self.profile_path.open(encoding="utf-8") as fh:
            on_disk = json.load(fh)
        self.assertEqual(on_disk["location"], "Garage")
        self.assertEqual(on_disk["unit_name"], "Garage Vortex")


# ─────────────────────────────────────────────────────────────────────────────
# Setup / pairing API
# ─────────────────────────────────────────────────────────────────────────────

class TestSetupAPI(unittest.TestCase):
    """Tests for core/setup_api.py — /api/vortex/v1/setup/* routes."""

    def setUp(self):
        from core.config import config
        from core.pairing import pairing_session
        from core.setup_api import router, set_restart_callback

        self.tmpdir = tempfile.TemporaryDirectory()
        self.profile_path = Path(self.tmpdir.name) / "vortex_profile.json"

        self.config = config
        self.pairing_session = pairing_session
        self.config.load(profile_path=str(self.profile_path))
        self.pairing_session.clear()

        self.restart_calls = 0

        def _restart():
            self.restart_calls += 1

        set_restart_callback(_restart)

        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        from core.constants import PROFILE_PATH
        from core.setup_api import set_restart_callback

        set_restart_callback(None)
        # Restore the singleton to point back at the repo's default profile.
        self.config.load(profile_path=PROFILE_PATH)
        self.tmpdir.cleanup()

    def test_info_when_unconfigured_includes_pairing_pin(self):
        resp = self.client.get("/api/vortex/v1/setup/info")
        self.assertEqual(resp.status_code, 200)

        data = resp.json()
        self.assertFalse(data["configured"])
        self.assertIn("pairing_pin", data)
        self.assertEqual(len(data["pairing_pin"]), 6)

    def test_pair_with_wrong_pin_is_rejected(self):
        self.client.get("/api/vortex/v1/setup/info")  # generates the PIN

        resp = self.client.post("/api/vortex/v1/setup/pair", json={
            "pin": "000000",
            "river_song_api_url": "http://riversong.local",
            "river_song_api_key": "key123",
        })

        self.assertEqual(resp.status_code, 403)
        self.assertFalse(self.config.get("configured"))
        self.assertEqual(self.restart_calls, 0)

    def test_pair_with_correct_pin_persists_config_and_restarts(self):
        info = self.client.get("/api/vortex/v1/setup/info").json()
        pin = info["pairing_pin"]

        resp = self.client.post("/api/vortex/v1/setup/pair", json={
            "pin": pin,
            "river_song_api_url": "http://riversong.local",
            "river_song_api_key": "key123",
            "unit_name": "Living Room Vortex",
            "location": "Living Room",
        })

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "paired")

        self.assertTrue(self.config.get("configured"))
        self.assertEqual(self.config.get("river_song_api_key"), "key123")
        self.assertEqual(self.config.get("unit_name"), "Living Room Vortex")
        self.assertEqual(self.config.get("location"), "Living Room")
        self.assertEqual(self.restart_calls, 1)

        # The PIN is single-use.
        self.assertIsNone(self.pairing_session.pin)

    def test_pair_when_already_configured_is_rejected(self):
        self.config.save_profile({"configured": True, "river_song_api_key": "existing-key"})

        resp = self.client.post("/api/vortex/v1/setup/pair", json={
            "pin": "123456",
            "river_song_api_url": "http://riversong.local",
            "river_song_api_key": "key123",
        })

        self.assertEqual(resp.status_code, 409)

    def test_unpair_requires_matching_api_key(self):
        self.config.save_profile({"configured": True, "river_song_api_key": "secret-key"})

        resp = self.client.post("/api/vortex/v1/setup/unpair", json={
            "river_song_api_key": "wrong-key",
        })

        self.assertEqual(resp.status_code, 403)
        self.assertTrue(self.config.get("configured"))

    def test_unpair_with_correct_key_returns_to_setup_mode(self):
        self.config.save_profile({"configured": True, "river_song_api_key": "secret-key"})

        resp = self.client.post("/api/vortex/v1/setup/unpair", json={
            "river_song_api_key": "secret-key",
        })

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(self.config.get("configured"))
        self.assertEqual(self.config.get("river_song_api_key"), "")
        self.assertEqual(self.restart_calls, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Discovery helpers
# ─────────────────────────────────────────────────────────────────────────────

class TestDiscoveryHelpers(unittest.TestCase):
    """Tests for connectivity/discovery.py helper functions."""

    def test_local_ip_address_returns_nonempty_string(self):
        from connectivity.discovery import _local_ip_address
        ip = _local_ip_address()
        self.assertIsInstance(ip, str)
        self.assertTrue(ip)

    def test_service_name_is_mdns_safe(self):
        from connectivity.discovery import _service_name
        from core.constants import MDNS_SERVICE_TYPE

        name = _service_name()
        self.assertTrue(name.endswith(f".{MDNS_SERVICE_TYPE}"))

        prefix = name[: -len(f".{MDNS_SERVICE_TYPE}")]
        self.assertNotEqual(prefix, "")
        self.assertTrue(all(c.isalnum() or c == "-" for c in prefix))
