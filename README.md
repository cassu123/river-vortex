# River Vortex

**River Vortex** is the physical device layer of the [River Song AI](https://riversongai.com) ecosystem — a dedicated smart home hub that places River Song's intelligence throughout your home via always-on display and voice devices. Think Google Home hub, but built for River Song.

---

## What It Does

| Capability | Details |
|---|---|
| **Always-on voice** | Wake word detection runs locally via Porcupine. No audio leaves the device until the wake word is confirmed. |
| **Ambient display** | Clock, weather, and notifications on a 7" or 10" touchscreen — always visible, always current. |
| **Device control** | Full Home Assistant integration — lights, thermostat, locks, covers, media players. |
| **Camera feeds** | Live snapshots and streams from all HA camera entities. |
| **Intercom** | Peer-to-peer audio between Vortex units in different rooms via UDP multicast. |
| **4G LTE fallback** | Automatic cellular failover when home WiFi is unavailable. |
| **Privacy controls** | Hardware GPIO LED indicators for mic and camera mute state. |

---

## Architecture

```
River Song AI (cloud/local AI)
        ↕  /api/vortex/v1/
River Vortex (this repo)
        ↕  WebSocket + REST
Home Assistant (smart home middleware)
        ↕
Smart home devices (lights, locks, cameras, etc.)
```

River Vortex is the **room interface layer only**. All AI processing is handled by River Song. Vortex captures voice, streams audio to River Song after wake word confirmation, and plays back the TTS response.

---

## Hardware

| Component | Supported Options |
|---|---|
| SBC | Raspberry Pi 4 or Pi 5 |
| Display | 7" (800×480) or 10" (1280×800) touchscreen |
| Microphone | USB mic array or ReSpeaker 4-mic HAT |
| Speaker | 3.5mm or USB audio |
| Network | WiFi (built-in) + optional USB 4G LTE dongle |

---

## Directory Structure

```
river-vortex/
├── core/               # Main entry point, config, constants
├── audio/              # Wake word (Porcupine), mic, speaker, audio manager
├── display/            # Screen manager, ambient mode, notifications, cameras
├── home_assistant/     # HA WebSocket client, device control, automation triggers
├── intercom/           # Peer-to-peer intercom, unit discovery (multicast)
├── connectivity/       # WiFi monitor, 4G LTE fallback, River Song API client
├── safety/             # Privacy manager (GPIO LEDs), system watchdog
├── telemetry/          # Structured logging, system metrics collector
├── frontend/           # React kiosk UI (Ambient, Dashboard, Devices, Cameras)
├── units/              # Per-unit vortex_profile.json
└── tests/              # Unit tests (audio, display, HA integration)
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 20+ (for frontend development)
- A running Home Assistant instance
- Porcupine access key — free at [console.picovoice.ai](https://console.picovoice.ai)

### 1. Clone and install

```bash
git clone https://github.com/your-org/river-vortex.git
cd river-vortex
pip install -r requirements.txt
```

### 2. Configure

Copy `.env.example` to `.env` and fill in your values:

```bash
# Required
HA_URL=http://homeassistant.local:8123
HA_TOKEN=your_long_lived_access_token
PORCUPINE_ACCESS_KEY=your_picovoice_key
RIVER_SONG_API_URL=http://riversong.local
RIVER_SONG_API_KEY=your_river_song_key

# Optional overrides
VORTEX_UNIT_NAME=Kitchen Vortex
VORTEX_LOCATION=Kitchen
LOG_LEVEL=INFO
```

Or edit `units/vortex_profile.json` directly for unit-specific settings.

### 3. Build the frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

### 4. Run

```bash
python -m core.main
```

The backend API is available at `http://localhost:8080/api/docs`.

### 5. Kiosk mode (on-device)

Launch Chromium in kiosk mode pointing at the local backend:

```bash
chromium-browser --kiosk --noerrdialogs --disable-infobars http://localhost:8080
```

---

## Configuration Priority

Settings are loaded in this order (later sources win):

1. Built-in defaults (`core/constants.py`)
2. `.env` file
3. `units/vortex_profile.json`
4. Environment variables (highest priority)

---

## Privacy

- Wake word detection is **always local** — Porcupine runs on-device, no audio is sent anywhere during detection.
- Audio is only streamed to River Song **after** the wake word is confirmed locally.
- Microphone and camera mute state is indicated by hardware GPIO LEDs — visible to the user at all times.
- The privacy manager can be toggled via voice command, the frontend, or the REST API.

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `HA_URL` | `http://homeassistant.local:8123` | Home Assistant base URL |
| `HA_TOKEN` | *(required)* | HA long-lived access token |
| `PORCUPINE_ACCESS_KEY` | *(required for wake word)* | Picovoice access key |
| `RIVER_SONG_API_URL` | `http://riversong.local` | River Song API base URL |
| `RIVER_SONG_API_KEY` | *(required for voice)* | River Song API key |
| `VORTEX_UNIT_ID` | `vortex-unset` | Unique unit identifier |
| `VORTEX_UNIT_NAME` | `River Vortex` | Display name for this unit |
| `VORTEX_LOCATION` | `Unknown Room` | Room location label |
| `VORTEX_WAKE_WORD` | `vortex` | Wake word (must match Porcupine model) |
| `VORTEX_VOLUME` | `70` | Speaker volume (0–100) |
| `VORTEX_AMBIENT_MODE` | `true` | Enable ambient mode |
| `VORTEX_LOG_LEVEL` | `INFO` | Logging level |
| `VORTEX_BACKEND_PORT` | `8080` | FastAPI server port |

---

## License

Internal Use Only — River Song AI / [riversongai.com](https://riversongai.com)
