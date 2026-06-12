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
| **Timers & alarms** | Voice-activated countdown timers with on-screen display and a chime when they elapse. |
| **Guided routines** | Step-by-step walkthroughs (cooking mode, workout mode, bedtime checklists) that duck background music and switch the display for the duration. |
| **Routine presets** | "Good Morning" / "Good Night" / "Leaving Home" style one-tap routines that activate a Home Assistant scene and start a guided checklist. |
| **Lists & reminders** | Shopping/to-do lists with tap-to-check items, and an on-screen banner for reminders due soon — synced live from River Song. |
| **Announcements / "Drop In"** | Broadcast a message to every Vortex unit (phone → house or room → room), with automatic media ducking and an on-screen banner. |
| **Intercom** | Peer-to-peer audio between Vortex units in different rooms via UDP multicast, with ringing/answer/decline call flow. |
| **4G LTE fallback** | Automatic cellular failover when home WiFi is unavailable. |
| **Privacy controls** | Hardware GPIO LED indicators for mic and camera mute state. |
| **Zero-touch setup** | Pairs with the River Song app like a Google Home device — discoverable via mDNS, paired with an on-screen PIN. No SSH or config files required. |

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
├── core/               # Entry point, config, constants, WS hub, timers, routines
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

Production units don't need this step — see [First-Run Pairing](#first-run-pairing-setup-mode)
below to set up the unit from the River Song app instead.

For local development, copy `.env.example` to `.env` and fill in your values:

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

## First-Run Pairing (Setup Mode)

A freshly-flashed Vortex unit ships **unpaired** — set up the same way you'd
set up a Google Home or Nest device, no SSH or `.env` editing required:

1. **Boot the unit.** With `"configured": false` (the default in
   `units/vortex_profile.json`), Vortex starts in **Setup mode**: the
   touchscreen shows a 6-digit pairing PIN, and the unit advertises itself
   on the local network via mDNS as `_riversong-vortex._tcp.local.`.
2. **Open the River Song app** (or browser) on a phone/computer connected to
   the same WiFi network. River Song discovers nearby unpaired Vortex units
   over mDNS.
3. **Enter the PIN** shown on the unit's display. River Song calls this
   unit's local setup API to deliver the River Song connection details (and
   optionally Home Assistant credentials, unit name, and location).
4. **The unit restarts automatically** with the new configuration applied,
   then boots straight into Ambient mode.

### Setup API

These endpoints are local-network only and unauthenticated by design — `/pair`
is gated by the on-screen PIN instead.

| Endpoint | Method | Description |
|---|---|---|
| `/api/vortex/v1/setup/info` | `GET` | Unit identity, hardware info, `configured` status, and (while unpaired) the current pairing PIN. |
| `/api/vortex/v1/setup/pair` | `POST` | Complete pairing: PIN + River Song (and optional HA/unit) settings. Persists to `vortex_profile.json` and restarts the unit. |
| `/api/vortex/v1/setup/unpair` | `POST` | Reset the unit back to Setup mode (requires the current `river_song_api_key`). |

### Re-pairing / factory reset

To return a unit to Setup mode, call `/api/vortex/v1/setup/unpair` with its
current `river_song_api_key`, or manually set `"configured": false` in
`units/vortex_profile.json` and restart.

### Headless / development setup

To skip pairing during development, set `RIVER_SONG_API_KEY` in `.env` — a
unit with this key already set is treated as configured and boots straight
into Ambient mode.

---

## Real-Time Events, Timers, Routines & Announcements

These features are driven by River Song's voice intent handlers, which call
the small REST APIs below. Vortex owns the countdown/step state, the
on-screen display, and (for routines/announcements) ducking background
media. See [ROADMAP.md](ROADMAP.md) for the full Alexa/Google Home feature
parity plan.

### WebSocket event hub — `/api/ws`

A single shared WebSocket endpoint that the React frontend connects to on
load. Every subsystem broadcasts JSON messages to all connected clients
through `core/ws_hub.py`. Relevant message types added in this phase:

| `type` | Payload | Sent when |
|---|---|---|
| `timers_update` | `{ "timers": [...] }` | A timer is created, cancelled, or elapses. |
| `timer_done` | `{ "timer": {...} }` | A timer reaches zero (also plays a chime). |
| `routine_update` | `{ "routine": {...} }` | A routine starts, advances, or stops. |
| `announcement` | `{ "announcement": {...} }` | A "Drop In" / broadcast announcement is made (`AnnouncementBanner`). |
| `intercom_update` | `{ "intercom": {...} }` | The room-to-room intercom state changes (idle/calling/ringing/active, `IntercomBanner`). |
| `lists_update` | `{ "lists": [...] }` | A list snapshot is pushed or a list item is toggled (`Lists` page). |
| `reminders_update` | `{ "reminders": [...] }` | A reminders snapshot is pushed (`ReminderBanner`). |

### Timers API — `/api/vortex/v1/timers`

| Endpoint | Method | Description |
|---|---|---|
| `/api/vortex/v1/timers` | `GET` | List all active timers/alarms. |
| `/api/vortex/v1/timers` | `POST` | Start a new timer: `{"duration_seconds": 600, "label": "Pasta"}`. |
| `/api/vortex/v1/timers/{timer_id}` | `DELETE` | Cancel an active timer. |

### Guided Routines API — `/api/vortex/v1/routine`

Used for cooking mode, workout mode, bedtime checklists, or any
step-by-step walkthrough.

| Endpoint | Method | Description |
|---|---|---|
| `/api/vortex/v1/routine` | `GET` | Current routine state (`{"active": false}` if none). |
| `/api/vortex/v1/routine` | `POST` | Start a routine: `{"title": "...", "steps": [{"instruction": "...", "duration_seconds": 540}]}`. Replaces any in-progress routine. |
| `/api/vortex/v1/routine/next` | `POST` | Advance to the next step (stops the routine on the last step). |
| `/api/vortex/v1/routine/previous` | `POST` | Go back one step (no-op on the first step). |
| `/api/vortex/v1/routine` | `DELETE` | End the routine early. |
| `/api/vortex/v1/routine/presets` | `GET` | List available routine preset templates (name, title, step count, optional scene). |
| `/api/vortex/v1/routine/presets/{name}` | `POST` | Activate a preset: best-effort activates its Home Assistant `scene` (if any), then starts its guided routine. `404` for an unknown preset name. |

While a routine is active, any currently-playing Home Assistant media
players are ducked to `ROUTINE_DUCK_VOLUME_LEVEL` (see `core/constants.py`)
and restored to their original volume when the routine ends. The display
switches to a dedicated "routine" mode for the duration.

Routine presets ("Good Morning", "Good Night", "Leaving Home", etc.) are
defined in `units/routine_presets.json` — edit freely per-unit to add your
own. Each preset has a `title`, ordered `steps` (same shape as the routine
API above), and an optional `scene` (a Home Assistant `scene.xxx` entity ID
activated before the routine starts).

### Lists & Reminders API — `/api/vortex/v1/lists` and `/api/vortex/v1/reminders`

Shopping/to-do lists and upcoming reminders are owned by River Song — Vortex
caches the latest snapshot for instant on-screen display and relays touch
actions back.

| Endpoint | Method | Description |
|---|---|---|
| `/api/vortex/v1/lists` | `GET` | Return the cached lists snapshot: `{"lists": [{"id", "name", "items": [{"id", "text", "checked"}, ...]}, ...]}`. |
| `/api/vortex/v1/lists` | `POST` | Replace the cached lists snapshot (pushed by River Song): `{"lists": [...]}`. Broadcasts `lists_update`. |
| `/api/vortex/v1/lists/{list_id}/items/{item_id}/toggle` | `POST` | Flip an item's `checked` state. Returns the updated list. `404` if the list or item doesn't exist. |
| `/api/vortex/v1/reminders` | `GET` | Return the cached reminders snapshot: `{"reminders": [{"id", "text", "due"}, ...]}`. |
| `/api/vortex/v1/reminders` | `POST` | Replace the cached reminders snapshot (pushed by River Song): `{"reminders": [...]}`. Broadcasts `reminders_update`. |

The frontend's `Lists` page renders the cached lists with tap-to-toggle
items, and `ReminderBanner` shows any reminder due within the next hour as
an on-screen card.

### Announcements ("Drop In") API — `/api/vortex/v1/announce`

| Endpoint | Method | Description |
|---|---|---|
| `/api/vortex/v1/announce` | `POST` | Broadcast a message: `{"message": "Dinner's ready!", "source": "Kitchen Vortex", "priority": "normal", "duration_seconds": 8}`. Returns `202` with the announcement (incl. `id` and `timestamp`). |

Phone → house and room → room broadcasts are both River Song fanning this
same call out to the relevant units — Vortex's only job is to play it
locally. House → phone notifications reuse the existing voice/notification
pipeline.

While an announcement plays, any currently-playing Home Assistant media
players are ducked to `ANNOUNCEMENT_DUCK_VOLUME_LEVEL` and restored once the
message's `duration_seconds` (or an estimate based on its length, capped at
`ANNOUNCEMENT_MAX_DURATION_SECONDS`) elapses. The "intercom" chime plays
first.

### Intercom ("Drop In" calls) API — `/api/vortex/v1/intercom`

| Endpoint | Method | Description |
|---|---|---|
| `/api/vortex/v1/intercom` | `GET` | Current call state: `{"state": "idle\|calling\|ringing\|active", "peer": {...} or null}`. |
| `/api/vortex/v1/intercom/peers` | `GET` | Other Vortex units discovered on the local network. |
| `/api/vortex/v1/intercom/call` | `POST` | Start a call: `{"peer_unit_id": "vortex-kitchen-01"}`. `409` if already on a call or the peer is unknown. |
| `/api/vortex/v1/intercom/answer` | `POST` | Answer an incoming (`ringing`) call. `409` if not ringing. |
| `/api/vortex/v1/intercom/decline` | `POST` | Decline an incoming (`ringing`) call. `409` if not ringing. |
| `/api/vortex/v1/intercom` | `DELETE` | Hang up / cancel the current call (idempotent). |

Once a call is `active`, audio streams directly between the two units over
UDP (raw PCM via `Microphone`/`Speaker`). Unanswered calls auto-cancel after
`INTERCOM_RING_TIMEOUT_SECONDS`; active calls auto-end after
`INTERCOM_MAX_CALL_DURATION_SECONDS`.

---

## Configuration Priority

Settings are loaded in this order (later sources win):

1. Built-in defaults (`core/constants.py`)
2. `.env` file
3. `units/vortex_profile.json`
4. Environment variables (highest priority)

The `configured` flag and `river_song_api_url` / `river_song_api_key` in
`units/vortex_profile.json` are normally written automatically by the
pairing flow above — see [First-Run Pairing](#first-run-pairing-setup-mode).

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
