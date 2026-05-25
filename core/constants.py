"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        core/constants.py
Purpose:     Centralized, immutable constants for the entire River Vortex system.
             All magic numbers, string literals, and configuration defaults live
             here. Import from this module — never hard-code values elsewhere.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

from enum import Enum, auto

# ─────────────────────────────────────────────────────────────────────────────
# System Identity
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_NAME: str = "River Vortex"
SYSTEM_CODENAME: str = "vortex"
VERSION: str = "1.0.0"
ECOSYSTEM: str = "River Song AI"
ECOSYSTEM_URL: str = "https://riversongai.com"

# ─────────────────────────────────────────────────────────────────────────────
# River Song API
# ─────────────────────────────────────────────────────────────────────────────

RIVER_SONG_API_BASE: str = "/api/vortex"
RIVER_SONG_API_VERSION: str = "v1"
RIVER_SONG_COMMAND_ENDPOINT: str = f"{RIVER_SONG_API_BASE}/{RIVER_SONG_API_VERSION}/command"
RIVER_SONG_STATUS_ENDPOINT: str = f"{RIVER_SONG_API_BASE}/{RIVER_SONG_API_VERSION}/status"
RIVER_SONG_STREAM_ENDPOINT: str = f"{RIVER_SONG_API_BASE}/{RIVER_SONG_API_VERSION}/stream"
RIVER_SONG_HEALTH_ENDPOINT: str = f"{RIVER_SONG_API_BASE}/{RIVER_SONG_API_VERSION}/health"

# API timeouts (seconds)
API_CONNECT_TIMEOUT: int = 5
API_READ_TIMEOUT: int = 30
API_STREAM_TIMEOUT: int = 120

# ─────────────────────────────────────────────────────────────────────────────
# Audio — Microphone & Wake Word
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_WAKE_WORD: str = "vortex"
WAKE_WORD_SENSITIVITY: float = 0.5          # 0.0 (strict) → 1.0 (permissive)
WAKE_WORD_COOLDOWN_SECONDS: float = 2.0     # Minimum gap between detections

SAMPLE_RATE: int = 16000                    # Hz — required by Porcupine
AUDIO_CHANNELS: int = 1                     # Mono
AUDIO_CHUNK_SIZE: int = 512                 # Frames per buffer read
AUDIO_FORMAT_BITS: int = 16                 # PCM 16-bit
AUDIO_DEVICE_INDEX: int = -1               # -1 = system default

# Audio streaming to River Song
STREAM_CHUNK_BYTES: int = 4096
MAX_COMMAND_DURATION_SECONDS: int = 30      # Hard cap on audio sent to River Song
SILENCE_THRESHOLD_RMS: int = 300            # RMS below this = silence
SILENCE_TIMEOUT_SECONDS: float = 2.0       # Seconds of silence before end-of-command

# ─────────────────────────────────────────────────────────────────────────────
# Audio — Speaker / Playback
# ─────────────────────────────────────────────────────────────────────────────

SPEAKER_SAMPLE_RATE: int = 44100
SPEAKER_CHANNELS: int = 2
DEFAULT_VOLUME: int = 70                    # Percent (0–100)
MIN_VOLUME: int = 0
MAX_VOLUME: int = 100
TTS_CACHE_DIR: str = "/tmp/vortex_tts_cache"

# ─────────────────────────────────────────────────────────────────────────────
# Display
# ─────────────────────────────────────────────────────────────────────────────

class ScreenSize(Enum):
    """Supported display resolutions."""
    SEVEN_INCH = (800, 480)
    TEN_INCH = (1280, 800)
    FULLHD = (1920, 1080)

SCREEN_WIDTH_DEFAULT: int = 1280
SCREEN_HEIGHT_DEFAULT: int = 800
SCREEN_ROTATION: int = 0                    # Degrees: 0, 90, 180, 270
SCREEN_BRIGHTNESS_DEFAULT: int = 80        # Percent
SCREEN_BRIGHTNESS_AMBIENT: int = 40        # Dimmed in ambient mode
SCREEN_BRIGHTNESS_MIN: int = 10
SCREEN_BRIGHTNESS_MAX: int = 100

AMBIENT_MODE_TIMEOUT_SECONDS: int = 300    # 5 min idle → ambient mode
AMBIENT_CLOCK_UPDATE_INTERVAL: int = 1     # Seconds between clock refreshes
AMBIENT_WEATHER_UPDATE_INTERVAL: int = 600 # 10 min between weather refreshes
NOTIFICATION_DISPLAY_DURATION: int = 8     # Seconds a notification stays visible
MAX_NOTIFICATIONS_DISPLAYED: int = 5

# ─────────────────────────────────────────────────────────────────────────────
# Home Assistant
# ─────────────────────────────────────────────────────────────────────────────

HA_WS_PATH: str = "/api/websocket"
HA_REST_PATH: str = "/api"
HA_RECONNECT_INTERVAL_SECONDS: int = 10
HA_MAX_RECONNECT_ATTEMPTS: int = 20
HA_PING_INTERVAL_SECONDS: int = 30
HA_COMMAND_TIMEOUT_SECONDS: int = 10

class HADomain(str, Enum):
    """Home Assistant service domains used by River Vortex."""
    LIGHT = "light"
    SWITCH = "switch"
    CLIMATE = "climate"
    LOCK = "lock"
    COVER = "cover"
    MEDIA_PLAYER = "media_player"
    CAMERA = "camera"
    AUTOMATION = "automation"
    SCRIPT = "script"
    SCENE = "scene"
    INPUT_BOOLEAN = "input_boolean"

class HAService(str, Enum):
    """Common Home Assistant service calls."""
    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    TOGGLE = "toggle"
    LOCK = "lock"
    UNLOCK = "unlock"
    OPEN_COVER = "open_cover"
    CLOSE_COVER = "close_cover"
    SET_TEMPERATURE = "set_temperature"
    VOLUME_SET = "volume_set"
    TRIGGER = "trigger"

# ─────────────────────────────────────────────────────────────────────────────
# Intercom
# ─────────────────────────────────────────────────────────────────────────────

INTERCOM_PORT: int = 5005
INTERCOM_DISCOVERY_PORT: int = 5006
INTERCOM_MULTICAST_GROUP: str = "239.255.42.99"
INTERCOM_DISCOVERY_INTERVAL_SECONDS: int = 30
INTERCOM_HEARTBEAT_INTERVAL_SECONDS: int = 15
INTERCOM_PEER_TIMEOUT_SECONDS: int = 60    # Remove peer if no heartbeat
INTERCOM_MAX_CALL_DURATION_SECONDS: int = 300
INTERCOM_AUDIO_SAMPLE_RATE: int = 16000
INTERCOM_AUDIO_CHANNELS: int = 1

# ─────────────────────────────────────────────────────────────────────────────
# Connectivity
# ─────────────────────────────────────────────────────────────────────────────

WIFI_CHECK_INTERVAL_SECONDS: int = 15
WIFI_RECONNECT_ATTEMPTS: int = 5
WIFI_RECONNECT_DELAY_SECONDS: int = 10

CELLULAR_CHECK_INTERVAL_SECONDS: int = 30
CELLULAR_FALLBACK_ENABLED: bool = True
CELLULAR_APN_DEFAULT: str = ""             # Set per carrier in profile

CONNECTIVITY_HEALTH_ENDPOINT: str = "https://1.1.1.1"  # Cloudflare DNS — fast ping
CONNECTIVITY_TIMEOUT_SECONDS: int = 5

# ─────────────────────────────────────────────────────────────────────────────
# Safety & Privacy
# ─────────────────────────────────────────────────────────────────────────────

PRIVACY_MIC_MUTE_GPIO_PIN: int = 17        # BCM pin for hardware mic mute LED
PRIVACY_CAM_MUTE_GPIO_PIN: int = 27        # BCM pin for hardware cam mute LED
WATCHDOG_HEARTBEAT_INTERVAL_SECONDS: int = 5
WATCHDOG_RESTART_DELAY_SECONDS: int = 3
WATCHDOG_MAX_RESTARTS: int = 5             # Per component per hour

# ─────────────────────────────────────────────────────────────────────────────
# Telemetry
# ─────────────────────────────────────────────────────────────────────────────

TELEMETRY_FLUSH_INTERVAL_SECONDS: int = 60
TELEMETRY_MAX_QUEUE_SIZE: int = 1000
LOG_ROTATION_SIZE_MB: int = 10
LOG_RETENTION_DAYS: int = 7
LOG_DIR: str = "/var/log/river-vortex"

# ─────────────────────────────────────────────────────────────────────────────
# System States
# ─────────────────────────────────────────────────────────────────────────────

class VortexState(Enum):
    """Top-level system states for the River Vortex unit."""
    INITIALIZING = auto()
    IDLE = auto()           # Ambient mode, listening for wake word
    LISTENING = auto()      # Wake word detected, capturing command
    PROCESSING = auto()     # Audio sent to River Song, awaiting response
    RESPONDING = auto()     # Playing TTS response
    INTERCOM = auto()       # Active intercom call
    ERROR = auto()
    SHUTTING_DOWN = auto()

class ConnectivityState(Enum):
    """Network connectivity states."""
    WIFI_CONNECTED = auto()
    WIFI_DISCONNECTED = auto()
    CELLULAR_ACTIVE = auto()
    OFFLINE = auto()

# ─────────────────────────────────────────────────────────────────────────────
# FastAPI / Backend Server
# ─────────────────────────────────────────────────────────────────────────────

BACKEND_HOST: str = "0.0.0.0"
BACKEND_PORT: int = 8080
BACKEND_RELOAD: bool = False               # Never True in production
BACKEND_WORKERS: int = 1                   # Single-core Pi — keep at 1
CORS_ALLOWED_ORIGINS: list = [
    "http://localhost:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]

# ─────────────────────────────────────────────────────────────────────────────
# File Paths
# ─────────────────────────────────────────────────────────────────────────────

PROFILE_PATH: str = "units/vortex_profile.json"
ENV_FILE_PATH: str = ".env"
PORCUPINE_MODEL_DIR: str = "audio/models"
FRONTEND_BUILD_DIR: str = "frontend/dist"
