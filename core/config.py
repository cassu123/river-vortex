"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/config.py
Purpose:     Configuration management for River Vortex. Loads settings from
             environment variables, .env file, and the unit's vortex_profile.json.
             Environment variables always take precedence over profile values.
             Provides a validated, typed singleton `config` used across the system.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from core.constants import (
    PROFILE_PATH,
    ENV_FILE_PATH,
    BACKEND_HOST,
    BACKEND_PORT,
    DEFAULT_WAKE_WORD,
    WAKE_WORD_SENSITIVITY,
    AMBIENT_MODE_TIMEOUT_SECONDS,
    SCREEN_BRIGHTNESS_DEFAULT,
    HA_RECONNECT_INTERVAL_SECONDS,
    INTERCOM_PORT,
    LOG_DIR,
)

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when a required configuration value is missing or invalid."""
    pass


class Config:
    """
    Singleton configuration manager for River Vortex.

    Load order (later sources override earlier ones):
      1. Built-in defaults (defined in constants.py)
      2. .env file (if present)
      3. vortex_profile.json (unit-specific overrides)
      4. Environment variables (highest priority — always wins)

    Usage:
        from core.config import config
        ha_url = config.get("ha_url")
        config.require("ha_token")   # raises ConfigError if missing/empty
    """

    def __init__(self) -> None:
        """Initialize Config with defaults. Call load() to populate fully."""
        self._settings: Dict[str, Any] = {}
        self._profile_path: Path = Path(PROFILE_PATH)
        self._loaded: bool = False

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def load(self, profile_path: Optional[str] = None) -> None:
        """
        Load all configuration sources in priority order.

        Args:
            profile_path: Optional override path to vortex_profile.json.
                          Defaults to the value in constants.PROFILE_PATH.
        """
        if profile_path:
            self._profile_path = Path(profile_path)

        # Step 1: Apply built-in defaults
        self._apply_defaults()

        # Step 2: Load .env file (does not override existing env vars)
        env_path = Path(ENV_FILE_PATH)
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
            logger.debug("Loaded .env from %s", env_path.resolve())
        else:
            logger.debug(".env file not found at %s — skipping", env_path.resolve())

        # Step 3: Load vortex_profile.json
        self._load_profile()

        # Step 4: Apply environment variable overrides (highest priority)
        self._apply_env_overrides()

        # A unit is considered "configured" once it has River Song credentials,
        # either from a completed pairing (persisted to the profile) or from
        # a manually-supplied RIVER_SONG_API_KEY (e.g., headless/dev setups).
        self._settings["configured"] = bool(self._settings.get("configured", False)) or bool(
            self._settings.get("river_song_api_key")
        )

        self._loaded = True
        logger.info(
            "Configuration loaded for unit '%s' at location '%s'",
            self._settings.get("unit_name", "unknown"),
            self._settings.get("location", "unknown"),
        )

    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a configuration value by key.

        Args:
            key:     The configuration key.
            default: Value to return if key is not found.

        Returns:
            The configuration value, or default if not present.
        """
        return self._settings.get(key, default)

    def require(self, key: str) -> Any:
        """
        Retrieve a required configuration value. Raises ConfigError if missing or empty.

        Args:
            key: The configuration key that must be present and non-empty.

        Returns:
            The configuration value.

        Raises:
            ConfigError: If the key is absent or its value is an empty string.
        """
        value = self._settings.get(key)
        if value is None or value == "":
            raise ConfigError(
                f"Required configuration key '{key}' is missing or empty. "
                f"Set it via environment variable or vortex_profile.json."
            )
        return value

    def set(self, key: str, value: Any) -> None:
        """
        Set a configuration value at runtime.

        This is intended for dynamic overrides (e.g., from the admin API).
        Changes are not persisted to disk.

        Args:
            key:   The configuration key.
            value: The new value.
        """
        logger.debug("Runtime config override: %s = %r", key, value)
        self._settings[key] = value

    def save_profile(self, updates: Dict[str, Any]) -> None:
        """
        Persist key/value updates to vortex_profile.json and reload configuration.

        Used by the setup/pairing API to write pairing results (River Song
        connection details, unit identity, etc.) back to disk so they survive
        restarts. Existing profile keys not present in `updates` are preserved.

        Args:
            updates: Flat dict of top-level profile keys to set or overwrite.
        """
        profile_data: Dict[str, Any] = {}
        if self._profile_path.exists():
            try:
                with self._profile_path.open("r", encoding="utf-8") as fh:
                    profile_data = json.load(fh)
            except (json.JSONDecodeError, OSError) as exc:
                logger.error(
                    "Could not read existing profile before save: %s — starting fresh.",
                    exc,
                )
                profile_data = {}

        profile_data.update(updates)

        self._profile_path.parent.mkdir(parents=True, exist_ok=True)
        with self._profile_path.open("w", encoding="utf-8") as fh:
            json.dump(profile_data, fh, indent=2)
            fh.write("\n")

        logger.info(
            "Profile saved to %s (%d key(s) updated).",
            self._profile_path.resolve(),
            len(updates),
        )

        self.load(profile_path=str(self._profile_path))

    def as_dict(self) -> Dict[str, Any]:
        """
        Return a copy of all settings as a plain dictionary.

        Sensitive keys (tokens, passwords) are redacted.

        Returns:
            A sanitized copy of the settings dict.
        """
        sensitive_keys = {"ha_token", "river_song_api_key", "unit_token"}
        return {
            k: ("***REDACTED***" if k in sensitive_keys else v)
            for k, v in self._settings.items()
        }

    def is_loaded(self) -> bool:
        """Return True if load() has been called successfully."""
        return self._loaded

    # ─────────────────────────────────────────────────────────────────────────
    # Private Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _apply_defaults(self) -> None:
        """
        Populate settings with safe built-in defaults.

        These are the fallback values used when no environment variable,
        .env entry, or profile key is present.
        """
        self._settings = {
            # Unit identity
            "unit_id": "vortex-unset",
            "unit_name": "River Vortex",
            "location": "Unknown Room",

            # Pairing — true once this unit has been paired with River Song
            "configured": False,

            # River Song API
            "river_song_api_url": os.getenv("RIVER_SONG_API_URL", "http://riversong.local"),
            "river_song_api_key": "",

            # Home Assistant
            "ha_url": "http://homeassistant.local:8123",
            "ha_token": "",
            "ha_reconnect_interval": HA_RECONNECT_INTERVAL_SECONDS,

            # Audio
            "wake_word": DEFAULT_WAKE_WORD,
            "wake_word_sensitivity": WAKE_WORD_SENSITIVITY,
            "porcupine_access_key": "",
            "audio_device_index": -1,
            "volume": 70,
            "mic_enabled": True,

            # Display
            "screen_width": 1280,
            "screen_height": 800,
            "screen_brightness": SCREEN_BRIGHTNESS_DEFAULT,
            "ambient_mode_enabled": True,
            "ambient_timeout": AMBIENT_MODE_TIMEOUT_SECONDS,
            "theme": "dark-river",

            # Physical shape of this unit: "hub_max" (10"), "hub" (7") or
            # "mini" (no screen at all). Drives which output surfaces the
            # presenter uses, and which layout the frontend picks.
            "form_factor": "hub",

            # Intercom
            "intercom_enabled": True,
            "intercom_port": INTERCOM_PORT,

            # Backend server
            "backend_host": BACKEND_HOST,
            "backend_port": BACKEND_PORT,

            # Logging
            "log_level": "INFO",
            "log_dir": LOG_DIR,

            # Privacy
            "privacy_mic_mute_on_startup": False,
            "privacy_cam_mute_on_startup": False,
        }

    def _load_profile(self) -> None:
        """
        Load and merge settings from vortex_profile.json.

        Profile values override defaults but are overridden by environment
        variables. Malformed JSON is logged and skipped — the system will
        continue with defaults rather than crash on a bad profile file.
        """
        if not self._profile_path.exists():
            logger.warning(
                "Unit profile not found at '%s'. Using defaults.",
                self._profile_path.resolve(),
            )
            return

        try:
            with self._profile_path.open("r", encoding="utf-8") as fh:
                profile_data: Dict[str, Any] = json.load(fh)
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse vortex_profile.json: %s — continuing with defaults.",
                exc,
            )
            return
        except OSError as exc:
            logger.error(
                "Could not read vortex_profile.json: %s — continuing with defaults.",
                exc,
            )
            return

        # Top-level scalar keys (unit_id, unit_name, location, theme, ...)
        self._settings.update({
            k: v for k, v in profile_data.items()
            if not isinstance(v, dict) and not k.startswith("_")
        })

        # Flatten grouped sections.
        #
        # The profile groups settings under "audio", "display", "intercom",
        # "privacy", "network", "backend" and "logging" purely for human
        # readability — the keys inside them are already unique and match the
        # flat names used everywhere else, so they merge straight in.
        # Previously these sections were dropped entirely, which meant every
        # value in the shipped profile silently had no effect.
        for section in ("audio", "display", "intercom", "privacy",
                        "network", "backend", "logging"):
            values = profile_data.get(section)
            if isinstance(values, dict):
                self._settings.update(values)

        # Sections that need renaming rather than a straight merge.
        capabilities: Dict[str, Any] = profile_data.get("capabilities", {})
        self._settings.update({
            "cap_audio": capabilities.get("audio", True),
            "cap_display": capabilities.get("display", True),
            "cap_intercom": capabilities.get("intercom", True),
            "cap_home_assistant": capabilities.get("home_assistant", True),
        })

        hardware: Dict[str, Any] = profile_data.get("hardware", {})
        self._settings.update({
            "hw_screen": hardware.get("screen", "unknown"),
            "hw_mic_array": hardware.get("mic_array", "unknown"),
            "hw_speakers": hardware.get("speakers", "unknown"),
            "hw_platform": hardware.get("platform", "unknown"),
        })
        # Screen dimensions live under hardware but are used flat.
        for key in ("screen_width", "screen_height"):
            if key in hardware:
                self._settings[key] = hardware[key]

        logger.debug(
            "Profile loaded: unit_id=%s, unit_name=%s",
            self._settings.get("unit_id"),
            self._settings.get("unit_name"),
        )

    def _apply_env_overrides(self) -> None:
        """
        Apply environment variable overrides with type coercion.

        Environment variables are always strings; this method converts them
        to the appropriate Python types based on the default value's type.
        """
        env_map: Dict[str, str] = {
            # env var name          → settings key
            "VORTEX_UNIT_ID":       "unit_id",
            "VORTEX_UNIT_NAME":     "unit_name",
            "VORTEX_LOCATION":      "location",
            "VORTEX_FORM_FACTOR":   "form_factor",
            "RIVER_SONG_API_URL":   "river_song_api_url",
            "RIVER_SONG_API_KEY":   "river_song_api_key",
            "HA_URL":               "ha_url",
            "HA_TOKEN":             "ha_token",
            "VORTEX_WAKE_WORD":     "wake_word",
            "PORCUPINE_ACCESS_KEY": "porcupine_access_key",
            "VORTEX_VOLUME":        "volume",
            "VORTEX_LOG_LEVEL":     "log_level",
            "VORTEX_LOG_DIR":       "log_dir",
            "VORTEX_BACKEND_PORT":  "backend_port",
        }

        bool_env_map: Dict[str, str] = {
            "VORTEX_AMBIENT_MODE":      "ambient_mode_enabled",
            "VORTEX_INTERCOM_ENABLED":  "intercom_enabled",
            "VORTEX_MIC_ENABLED":       "mic_enabled",
        }

        for env_key, settings_key in env_map.items():
            raw = os.getenv(env_key)
            if raw is not None:
                # Coerce to the type of the existing default
                existing = self._settings.get(settings_key)
                self._settings[settings_key] = self._coerce(raw, type(existing))

        for env_key, settings_key in bool_env_map.items():
            raw = os.getenv(env_key)
            if raw is not None:
                self._settings[settings_key] = raw.strip().lower() in ("1", "true", "yes")

    @staticmethod
    def _coerce(value: str, target_type: type) -> Any:
        """
        Coerce a string value to the given target type.

        Args:
            value:       The raw string from an environment variable.
            target_type: The Python type to coerce to.

        Returns:
            The coerced value, or the original string if coercion fails.
        """
        try:
            if target_type is bool:
                return value.strip().lower() in ("1", "true", "yes")
            if target_type is int:
                return int(value)
            if target_type is float:
                return float(value)
        except (ValueError, TypeError):
            logger.warning(
                "Could not coerce env value '%s' to %s — using raw string.",
                value,
                target_type.__name__,
            )
        return value


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton — import this everywhere
# ─────────────────────────────────────────────────────────────────────────────

config = Config()
