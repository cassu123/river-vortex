# River Vortex

**River Vortex** is the physical device layer of the [River Song AI](https://riversongai.com) ecosystem — a dedicated smart home hub that places River Song's intelligence throughout your home via always-on display and voice devices. Think Google Home hub, but built for River Song.

---

## What It Does

| Capability | Details |
|---|---|
| **Always-on voice** | Wake word detection runs locally. No audio leaves the device until the wake word is confirmed. |
| **River's presence** | An animated orb shows what River is doing — listening, thinking, speaking. Driven live by the voice pipeline. One shared contract, so the 3D avatar later drops into the same slot. |
| **Ambient display** | Clock, weather and photos on a 7" or 10" touchscreen, plus whatever River has decided matters right now (see [Surfaces](#surfaces--api-vortex-v1-surfaces)). |
| **Surfaces** | River Song pushes a card — bin day, garage still open, someone at the door — and the unit renders it. The unit holds no opinion about what deserves the screen. |
| **Screenless units** | The same image runs on a display-less "Mini". Anything the screen would show is spoken instead, decided in one place (`core/presenter.py`). |
| **Boot self-test** | A cyberpunk boot screen running 13 **real** hardware checks. Nothing is on a timer; a line reading `FAIL` means that capability genuinely is not working. |
| **Burn-in protection** | Four stages — active → ambient → drifting screensaver → backlight off. The last one actually cuts `bl_power`, not brightness to zero. |
| **Photo backdrop** | A local photo library crossfades behind the clock, Nest Hub style. Local-first, so it keeps working with River Song down. |
| **Media playback** | Streaming music and radio via `mpv`, with transport controls, a queue, and ducking for timers, routines and announcements. |
| **Device control** | ⚠️ **UI only.** The grid and toggles are built; nothing feeds them devices yet. Locks are *designed* to be hard-denied by voice on the server — also not implemented there. |
| **Camera feeds** | ⚠️ **UI only.** Same gap — the page renders, nothing supplies the HA camera list. |
| **Timers & alarms** | Voice-activated countdown timers with on-screen display and a chime when they elapse. |
| **Guided routines** | Step-by-step walkthroughs (cooking mode, workout mode, bedtime checklists) that duck background music and switch the display for the duration. |
| **Routine presets** | "Good Morning" / "Good Night" / "Leaving Home" style one-tap routines that activate a Home Assistant scene and start a guided checklist. |
| **Lists & reminders** | Shopping/to-do lists with tap-to-check items, and an on-screen banner for reminders due soon — synced live from River Song. |
| **Announcements / "Drop In"** | Broadcast a message to every Vortex unit (phone → house or room → room), with automatic media ducking and an on-screen banner. |
| **Intercom** | Peer-to-peer audio between Vortex units in different rooms via UDP multicast, with ringing/answer/decline call flow. |
| **Privacy controls** | Hardware GPIO LED indicators for mic and camera mute state. |
| **Zero-touch setup** | Pairs with the River Song app like a Google Home device — discoverable via mDNS, paired with an on-screen PIN. No SSH or config files required. A unit in its box claims no room name until it is set up. |

---

## Architecture

```
River Song AI (the server — owns all the thinking)
        ↕  /api/vortex/v1/  +  WebSocket
River Vortex (this repo — the room interface)
        ↕  WebSocket + REST
Home Assistant (smart home middleware)
        ↕
Smart home devices (lights, covers, cameras, etc.)
```

River Vortex is the **room interface layer only**. All AI processing happens on
River Song. Vortex captures voice, streams it up after the wake word is
confirmed locally, and plays back the response.

The same split governs the screen. River Song knows the room, the time, who is
home and what is cooking; it decides *what* is worth showing and pushes a card.
Vortex knows the panel, the backlight and the speaker; it decides *how* to show
it. That is why a new kind of "what matters now" is a server-side change rather
than a software update on every unit in the house.

### One image, two shapes of unit

Every unit runs the same code. A screened Hub and a screenless Mini differ only
in what `core/presenter.py` does with an event:

| | Hub / Hub Max | Mini (no screen) |
|---|---|---|
| Timer finishes | banner **and** spoken | spoken |
| Recipe step | shown **and** spoken | spoken |
| List refresh | shown | silent — carries no phrase |
| Ordinary surface card | shown | spoken, if it carries `speech` |
| Urgent surface card | shown **and** spoken | spoken |

Speech itself degrades in three tiers: River Song's TTS → offline `espeak-ng`
→ a chime. A unit that has lost the network still tells you the pasta is done.

---

## Hardware

| Component | Supported Options |
|---|---|
| SBC | Raspberry Pi 4 or Pi 5 |
| Display | 7" (800×480) or 10" (1280×800) touchscreen, landscape or portrait — or none at all |
| Microphone | USB mic array or ReSpeaker 4-mic HAT |
| Speaker | 3.5mm or USB audio |
| Network | WiFi (built-in). **No cellular** — units are WiFi-only by design. |

No AI accelerator is needed. Every model runs on the River Song server, which
is what keeps a Pi 4 a perfectly good unit.

### Performance contract

The kiosk UI runs 16 hours a day on a Pi 4, so the frontend holds to a rule
that is enforced by convention in `presence/orb.css` and `surfaces/surfaces.css`:

- animate **only** `transform` and `opacity`
- never animate `filter`, `box-shadow`, `width`/`height` or `background`
- glow is baked into static gradients, not blur filters
- the live TTS amplitude is carried in a ref, never React state — a 30Hz
  envelope must not enter the render cycle

Breaking this is the difference between 0% and 40% CPU at idle.

---

## Directory Structure

```
river-vortex/
├── core/               # Entry point, config, WS hub, presenter, voice,
│                       #   diagnostics, timers, routines, surfaces
├── audio/              # Wake word, mic, speaker, audio manager, mpv media player
├── display/            # Screen manager (burn-in stages), ambient mode,
│                       #   photo library, notifications, cameras
├── home_assistant/     # HA WebSocket client, device control, automation triggers
├── intercom/           # Peer-to-peer intercom, unit discovery (multicast)
├── connectivity/       # WiFi monitor, River Song API client, mDNS discovery
├── safety/             # Privacy manager (GPIO LEDs), system watchdog
├── telemetry/          # Structured logging, system metrics collector
├── frontend/src/
│   ├── pages/          # Boot, Ambient, Dashboard, Devices, Cameras,
│   │                   #   Routine, Lists, NowPlaying, Screensaver, Setup
│   ├── presence/       # River's orb + the presence contract
│   ├── surfaces/       # Surface contract, card renderer, card CSS
│   └── components/     # Clock, Weather, PhotoBackdrop, banners, widgets
├── units/              # Per-unit vortex_profile.json (identity written at pairing)
└── tests/              # Unit tests
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 20+ (for frontend development)
- A running Home Assistant instance
- Porcupine access key — free at [console.picovoice.ai](https://console.picovoice.ai)
- Two system packages, neither of which is a pip install:

  ```bash
  sudo apt install mpv espeak-ng
  ```

  `mpv` plays streaming media; `espeak-ng` is the offline speech fallback used
  when River Song is unreachable. Both are optional — the boot self-test
  reports `WARN` and the unit runs without them, just quieter.

### 1. Clone and install

```bash
git clone https://github.com/cassu123/river-vortex.git
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

## API Reference

Everything below is driven by River Song, which calls these small typed REST
APIs under `/api/vortex/v1/`. Vortex owns the local state — countdowns, recipe
steps, ducked volumes, what is on the panel — and pushes every change to the
frontend over one WebSocket.

Nothing here does intent recognition. River Song decides *what* to do; these
endpoints are *how* it happens on this device.

See [ROADMAP.md](ROADMAP.md) for what is built, what is blocked, and what has
not been started.

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
| `surface` | `{ "surface": {...} }` | River Song pushes a card to show (`Surface`). Replaces any card with the same `id`. |
| `surface_remove` | `{ "id": "..." }` | A card is withdrawn before it expires. |
| `surfaces_update` | `{ "surfaces": [...] }` | The whole card set is replaced (currently only on clear). |
| `presence` | `{ "data": {"state": "LISTENING"} }` | River's state changes — drives the orb. Sent by `AudioManager._set_state`; the frontend maps `VortexState` names itself. |
| `amplitude` | `{ "value": 0.0–1.0 }` | Live TTS envelope, ~30Hz. Written to a ref, deliberately **not** dispatched. ⚠️ Nothing sends it yet, so `speaking` cannot pulse. |
| `media_update` | `{ "media": {...} }` | Playback state changes (`NowPlaying`). |
| `diagnostic` | `{ "result": {...}, "report": {...} }` | A boot self-test check finished (`Boot`). |
| `ambient_update` | `{ "data": {...} }` | Clock/date/weather refresh. |
| `navigate` | `{ "page": "..." }` | The backend moves the display to another page, including the burn-in stages. |

<a name="surfaces--api-vortex-v1-surfaces"></a>
### Surfaces — `/api/vortex/v1/surfaces`

How River Song drives the ambient screen. A **surface** is a small declarative
card: a kind, a payload, a priority and a lifetime. River Song pushes one when
something becomes true and withdraws it when it stops being true; the unit
draws it and orders it against whatever else is up.

The unit never decides what deserves the screen. Making that call needs the
room, the time, who is home and what is cooking — context that only exists on
the server. What the unit owns is how a card looks, how it is spoken on a Mini,
and when it comes down.

| Endpoint | Method | Description |
|---|---|---|
| `/api/vortex/v1/surfaces` | `GET` | Live cards, most important first. The kiosk reads this on load so a browser restart does not blank the screen. |
| `/api/vortex/v1/surfaces` | `POST` | Show or replace a card. Returns `202`. |
| `/api/vortex/v1/surfaces/{id}` | `DELETE` | Withdraw a card early. `404` if it is not up. |
| `/api/vortex/v1/surfaces` | `DELETE` | Clear every card (used when a unit is unpaired). |
| `/api/vortex/v1/surfaces/{id}/action` | `POST` | A button was tapped: `{"intent": "..."}`. Relayed to River Song verbatim; `502` if it does not land. |

```jsonc
{
  "id": "garage",          // stable — pushing the same id REPLACES, never stacks
  "kind": "alert",         // note | list | stat | media | image | alert | confirm
  "priority": "high",      // ambient | normal | high | critical
  "title": "Garage door still open",
  "body": "It's been open for 40 minutes.",
  "value": "4", "unit": "°C",             // stat only
  "items": ["Milk", "Coffee"],             // list only, max 8
  "image_url": "...", "icon": "⚠",
  "actions": [                             // max 3
    {"label": "Close it", "intent": "cover.close.garage", "style": "primary"}
  ],
  "ttl_seconds": 900,
  "speech": "The garage has been open for forty minutes."
}
```

**Priority is physical, not decorative:**

| Priority | Effect |
|---|---|
| `ambient` | Idle filler. Shown only when nothing else wants the screen. |
| `normal` | Sits beside the clock on the ambient page. |
| `high` | **Wakes the screen** from screensaver or backlight-off, **and is spoken aloud even on a unit that has a display.** |
| `critical` | All of the above, plus takes over the whole panel over any page, and cuts off whatever audio is playing. |

`high` and `critical` are real interruptions in a bedroom at 3am. They are for
doorbells, smoke and water — not for a delivery notification.

`speech` is what carries a card to a screenless Mini, which has no other way to
receive it at all. A card with no `speech` is invisible on a Mini.

**Buttons are prompts, not authorisations.** Tapping one relays the `intent`
string to River Song untouched; the unit never parses or acts on it. River Song
re-runs it through the same permission checks as a spoken command, including
the hard deny on locks. The card only comes down once River Song accepts it, so
a tap that never arrived does not look like one that did.

Lifetimes are absolute deadlines, not countdowns, so a suspended kiosk does not
come back with an hour still on the clock. The store is capped at 32 cards and
sheds the least important oldest first.

The server half — the room-aware publisher that decides which unit gets which
card, and the `/api/vortex/v1/surface-action` endpoint the unit already calls —
lives in River Song and is not built yet.

### Boot self-test — `/api/vortex/v1/diagnostics`

A wall-mounted unit has no keyboard, so it needs somewhere to say what is
wrong. On boot it runs 13 real checks and prints them as they finish:

```
CORE RUNTIME · CONFIGURATION · STORAGE · MEMORY · THERMAL · POWER · DISPLAY
AUDIO OUTPUT · MICROPHONE · SPEECH SYNTH · MEDIA ENGINE · NETWORK LINK
RIVER SONG UPLINK
```

Nothing is faked. The pauses on screen are the checks actually taking that
long, a `FAIL` means that capability genuinely is not working, and the unit
still boots on `WARN` — degraded is not broken.

| Endpoint | Method | Description |
|---|---|---|
| `/api/vortex/v1/diagnostics` | `GET` | The latest report: `results`, `counts`, `complete`, `healthy`, `elapsed_ms`. |
| `/api/vortex/v1/diagnostics/run` | `POST` | Re-run the self-test. |

Each result also streams over `/api/ws` as a `diagnostic` message, so the boot
screen fills in progressively rather than appearing all at once.

### Media — `/api/vortex/v1/media`

Streaming music and radio play on **this unit's speaker**, through a resident
`mpv` child process driven over its JSON IPC socket. River Song resolves a
spoken request into a stream URL and posts it here; the touchscreen drives the
same endpoints, so voice and touch control one player.

| Endpoint | Method | Description |
|---|---|---|
| `/api/vortex/v1/media` | `GET` | Transport state and `now_playing`. |
| `/api/vortex/v1/media/play` | `POST` | Play a track or queue: `{"url", "title", "artist", "artwork_url"}`. |
| `/api/vortex/v1/media/pause` · `/resume` · `/toggle` | `POST` | Transport control. |
| `/api/vortex/v1/media/next` · `/previous` | `POST` | Move through the queue. |
| `/api/vortex/v1/media/volume` | `POST` | Set volume `0.0–1.0`. |
| `/api/vortex/v1/media` | `DELETE` | Stop and clear the queue. |

Ducking is idempotent — a timer, a routine and an announcement overlapping
cannot stack four volume reductions and leave the music inaudible afterwards.

### Ambient photos — `/api/vortex/v1/photos`

Photos live **on the unit**, so the backdrop keeps working when River Song is
down or WiFi has dropped. A changing backdrop is also the opposite of a static
burned-in layout.

| Endpoint | Method | Description |
|---|---|---|
| `/api/vortex/v1/photos` | `GET` | The playlist and hold interval. |
| `/api/vortex/v1/photos/file/{name}` | `GET` | One image, served by **name match against the scanned library** — never by path join, so there is no traversal to exploit. |
| `/api/vortex/v1/photos/rescan` | `POST` | Pick up files added to the photo directory. |

An empty or missing photo directory is fine: the screen falls back to the plain
gradient. A unit with no photos should look deliberate, not broken.

### Burn-in protection

An always-on panel dies if it shows the same layout forever, so the display
steps down through four stages measured from the **last activity**:

| Stage | Default | What it does |
|---|---|---|
| active | — | Full brightness, whatever page is open |
| ambient | — | Dimmed clock, weather, photos, surfaces |
| screensaver | 30 min | A very dim clock that drifts around the panel every 45s |
| off | 90 min | Cuts the backlight via `bl_power` — the only stage that genuinely stops wear and saves power |

The frontend still renders black underneath the `off` stage, so waking does not
flash the previous screen before the next one paints. Tuned in
`core/constants.py`; a `high` or `critical` surface wakes the panel straight
back to ambient.

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

## Privacy & Trust Boundaries

- Wake word detection is **always local** — it runs on-device, and no audio is
  sent anywhere during detection.
- Audio is only streamed to River Song **after** the wake word is confirmed
  locally.
- Microphone and camera mute state is indicated by hardware GPIO LEDs —
  visible to the user at all times.
- The privacy manager can be toggled via voice command, the frontend, or the
  REST API.

**A unit is not trusted with permission decisions.** Everything that could
matter is decided on the server:

- **Locks, garage doors and alarm disarm are hard-denied to Vortex units** in
  River Song's intent router — not merely gated behind a confirmation. A Pi
  stolen out of a kitchen must not be able to open a door.
- A `confirm` surface card is a prompt. Tapping it relays an opaque intent
  string upward; the unit cannot act on it, so the card is not a second,
  weaker permission system sitting on the wall.
- Second factors are entered **on the touchscreen**, never spoken. A spoken PIN
  travels the same channel as the voice that triggered it and is audible to the
  whole room, so it adds no real factor.
- Photo files are served by name match against the scanned library. There is no
  path joining, so there is no traversal.

All of these are enforced in River Song, not here. A unit that could enforce
its own permissions would be a unit worth stealing.

---

## Running Tests

```bash
pytest tests/ -v
```

Or without pytest installed:

```bash
python -m unittest $(ls tests/test_*.py | sed 's|/|.|;s|\.py$||')
```

`tests/test_audio.py` needs `PyAudio`, which does not install on every
development machine. Everything else runs anywhere.

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `HA_URL` | `http://homeassistant.local:8123` | Home Assistant base URL |
| `HA_TOKEN` | *(required)* | HA long-lived access token |
| `PORCUPINE_ACCESS_KEY` | *(required for wake word)* | Picovoice access key |
| `RIVER_SONG_API_URL` | `http://riversong.local` | River Song API base URL |
| `RIVER_SONG_API_KEY` | *(required for voice)* | River Song API key |
| `VORTEX_UNIT_ID` | *(derived per-device)* | Unique unit identifier — see below |
| `VORTEX_UNIT_NAME` | *(unset until paired)* | Display name for this unit |
| `VORTEX_LOCATION` | *(unset until paired)* | Room location label |
| `VORTEX_WAKE_WORD` | `vortex` | Wake word (must match the Porcupine model) |
| `VORTEX_VOLUME` | `70` | Speaker volume (0–100) |
| `VORTEX_AMBIENT_MODE` | `true` | Enable ambient mode |
| `VORTEX_LOG_LEVEL` | `INFO` | Logging level |
| `VORTEX_BACKEND_PORT` | `8080` | FastAPI server port |

### Unit identity

`unit_id` is **derived on the device**, from the Pi's CPU serial, falling back
to a MAC address, falling back to random. Every unit is flashed from the same
image, so an id baked into that image would make every hub in the house the
same hub.

Name and location are deliberately absent until pairing writes them. A unit
still in its box does not claim to be the kitchen — the boot screen reports
`unpaired` rather than inventing a room.

---

## What Is Not Finished

Kept honest on purpose — everything above is built and tested, everything here
is not.

### Waiting on River Song

These have a working Vortex half that calls an endpoint the server does not
serve yet:

| Feature | What is missing |
|---|---|
| Surface publisher | The room-aware server side that decides which unit gets which card, plus `/api/vortex/v1/surface-action` for tapped buttons. |
| River's voice | `core/voice.py` probes for a TTS endpoint that does not exist, so every unit falls through to robotic offline espeak-ng instead of River. |
| Weather on units | The feeds API authenticates a *user*; a unit holds a *unit* token, so it cannot call it. The widget shows "Weather loading…" until this is resolved. |
| Device / camera / notification data | Nothing feeds the grids. Should come from River Song's Home Assistant layer, not this repo's duplicate. |
| Music resolution | River Song's YouTube Music provider plays on the server box. It needs to hand a stream URL back so the sound comes out of the unit you asked. |
| `/api/vortex/ws` | The persistent uplink, so units are pushed to rather than polling — and the source of the orb's missing amplitude stream. |
| Replica sync | Local mirror of River Song state, so a unit stays useful while the server reboots. |
| Cooking sessions | Server-owned recipe state, so a session can follow you between rooms. |
| Pairing endpoints | The unauthenticated device half of the claim flow. |
| Security fixes | Constant-time token compare, hashing tokens at rest, and the lock hard-deny. |
| Camera features | Face matching, video call signalling, occupancy routing, motion snapshots. The device capture layer is built and waiting. |

### Broken seams on this side

Found by diffing the WebSocket messages the frontend handles against the ones
the backend sends. All the same shape: both halves written, nothing joining
them. The orb and the offline-speech seams are now fixed; these are not.

- **The device, camera and notification screens have no data source.**
  `state.devices`, `state.cameras` and `state.notifications` are populated only
  by `devices_update` / `cameras_update` / `notifications_update`, and nothing
  sends any of them. There is no REST endpoint either, and `/api/devices/toggle`
  — which `DeviceGrid` POSTs to — does not exist. So "Device control" and
  "Camera feeds" in the table above are **UI only**: the pages render, the grid
  is empty.
- **Nothing measures the TTS envelope**, so the orb's `speaking` state cannot
  pulse and looks identical to `listening`.
- **No full-size orb on the ambient screen** — only the small corner overlay,
  on the screen the unit shows most of the time.

The first of those is one decision rather than three: the data should come
from River Song's Home Assistant layer, not from this repo's duplicated
`home_assistant/` package.

### Not started here

- **openWakeWord** — River Song already uses it, and the wake word is chosen in
  the user's profile there. Vortex still ships Porcupine, so the two do not yet
  agree on what "hey River" means.
- **The duplicated `home_assistant/` package** — 824 lines of HA client that
  River Song already owns. It should be called through, not reimplemented.
- **SoftAP provisioning** — for changing WiFi after a house move, without
  re-pairing every unit.
- **Pi image work** — hiding the rainbow splash and the boot text, so the first
  thing on screen is the Vortex self-test.
- **Casting** — there is no official Google Cast REST API. The practical route
  is `pychromecast` through Home Assistant, which River Song already owns.
- **The 3D avatar** — the orb is the first renderer for the presence contract;
  the avatar drops into the same slot without touching anything upstream of it.

---

## License

Internal Use Only — River Song AI / [riversongai.com](https://riversongai.com)
