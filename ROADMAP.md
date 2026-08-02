# River Vortex — Feature Roadmap: Alexa / Google Home Parity

This roadmap tracks the features needed to bring River Vortex to feature
parity with Amazon Alexa / Google Home devices — guided routines, timers,
multi-room audio, lists, reminders, and proactive notifications.

## Architecture Principle

River Vortex stays a **thin device layer**. River Song (the cloud AI) owns
all natural-language understanding and orchestration logic — recognizing
voice intents like "set a timer for 10 minutes," "start the lasagna recipe,"
"next step," or "what's on my shopping list." Vortex exposes small, typed
REST APIs under `/api/vortex/v1/...` that River Song calls, and Vortex owns:

- Local state machines (timers, routine steps, ducked media volumes)
- The on-screen display (React frontend, pushed live via `/api/ws`)
- Direct hardware/Home Assistant actions (chimes, volume ducking, lights)

Vortex does **not** need local intent recognition — River Song decides
*what* to do, Vortex handles *how* to do it on this device.

---

## Phase 1 — Real-Time Layer, Timers & Cooking Mode ✅ DONE

**Goal:** Lay the WebSocket foundation every later phase needs, then ship the
two most-used Alexa/Google Home features: kitchen timers/alarms and guided
step-by-step routines (cooking mode, workout mode, bedtime checklists) with
automatic background-music ducking.

- **WebSocket broadcast hub** (`core/ws_hub.py`, `/api/ws`)
  - Shared `ConnectionManager` singleton (`ws_hub`) — any subsystem can
    `await ws_hub.broadcast({...})` to push a JSON event to every connected
    frontend client.
- **Timers & Alarms** (`core/timers.py`, `core/timers_api.py`)
  - `GET/POST /api/vortex/v1/timers`, `DELETE /api/vortex/v1/timers/{id}`
  - Async countdown per timer; on completion, plays a chime
    (`AudioManager.play_chime("done")`) and broadcasts `timer_done` /
    `timers_update` over `/api/ws`.
- **Guided Routines / Cooking Mode** (`core/routines.py`, `core/routines_api.py`)
  - `GET/POST/DELETE /api/vortex/v1/routine`,
    `POST /api/vortex/v1/routine/next`, `POST /api/vortex/v1/routine/previous`
  - Switches the display to a dedicated "routine" mode for the duration.
  - **Ducks any currently-playing Home Assistant media players** to
    `ROUTINE_DUCK_VOLUME_LEVEL` when a routine starts, and restores their
    original volume when it ends.
  - Broadcasts `routine_update` over `/api/ws` on every step change.
- **Frontend**
  - New `Routine` page — title, step progress dots, large instruction text,
    per-step "start timer" shortcut, and Back/Next/End touch controls.
  - New `TimersWidget` — floating live countdowns with tap-to-cancel and a
    "time's up" banner, shown on Ambient/Dashboard/Routine.
  - `App.jsx` now handles `timers_update`, `timer_done`, and
    `routine_update` WebSocket messages.
- **Tests:** `tests/test_ws_hub.py`, `tests/test_timers.py`,
  `tests/test_routines.py` (+ `AudioManager.play_chime`).

---

## Phase 2 — Multi-Room Audio & Announcements ("Drop In") ✅ DONE

**Goal:** "Announce to all rooms" and "Drop In" on a specific room, the way
Alexa/Google Home broadcast across a household.

- **Announcements** (`core/announce.py`, `core/announce_api.py`)
  - `POST /api/vortex/v1/announce` — River Song (or the River Song phone app,
    via River Song) posts a message; Vortex ducks any currently-playing media
    (`ANNOUNCEMENT_DUCK_VOLUME_LEVEL`), plays the "intercom" chime, broadcasts
    an `announcement` event over `/api/ws`, and restores media volume after
    the message's estimated/explicit duration. Covers phone → house
    broadcasts and room → room messages (River Song fans the request out to
    every unit). House → phone notifications reuse the existing voice/
    notification pipeline — no new Vortex API needed.
  - Overlapping announcements don't double-duck; ducked volumes are restored
    once the last announcement's timer elapses.
- **Room-to-Room Intercom / "Drop In"** (`intercom/intercom_manager.py`,
  `core/intercom_api.py`)
  - `GET /api/vortex/v1/intercom` (state), `GET /api/vortex/v1/intercom/peers`
    (discoverable units), `POST /api/vortex/v1/intercom/call`,
    `POST /api/vortex/v1/intercom/answer`, `POST /api/vortex/v1/intercom/decline`,
    `DELETE /api/vortex/v1/intercom` (hang up).
  - Full UDP call-signaling protocol (`call_request` / `call_accept` /
    `call_decline` / `call_busy` / `call_end`) plus a live two-way raw PCM
    audio stream once a call is active, using the existing
    `Microphone`/`Speaker` I/O (`Speaker.play_raw` / `Speaker.stop_raw`).
  - Unanswered calls auto-cancel after `INTERCOM_RING_TIMEOUT_SECONDS`; active
    calls auto-end after `INTERCOM_MAX_CALL_DURATION_SECONDS`.
  - Incoming calls play the "intercom" chime and switch the display to the
    dashboard.
- Broadcasts `announcement` and `intercom_update` events over `/api/ws` so the
  frontend shows "📢 Announcement" / "📞 Drop In from Kitchen" overlays
  (`AnnouncementBanner`, `IntercomBanner`).
- **Tests:** `tests/test_announce.py`, `tests/test_intercom.py`.

---

## Phase 3 — Lists & Reminders Display Surface ✅ DONE

**Goal:** Shopping lists, to-do lists, and reminders visible and
checkable/snoozable from the touchscreen — data is owned by River Song,
Vortex just displays the latest snapshot and relays touch actions.

- **Lists & Reminders cache** (`core/lists.py`, `core/lists_api.py`)
  - `GET/POST /api/vortex/v1/lists`,
    `POST /api/vortex/v1/lists/{list_id}/items/{item_id}/toggle` — thin
    pass-through that Vortex caches locally (`ListsStore`) for instant
    display and forwards to River Song for persistence.
  - `GET/POST /api/vortex/v1/reminders` — same thin-cache pattern for
    upcoming reminders.
  - Broadcasts `lists_update` / `reminders_update` over `/api/ws` whenever
    the snapshot changes or an item is toggled.
- **Frontend**
  - New `Lists` page — checklist UI grouped by list, tap-to-toggle items,
    styled like `Routine`. Reachable via a new "📝 Lists" dashboard nav tab.
  - New `ReminderBanner` — shows reminders due within the next hour as a
    small overlay card, similar in style to `NotificationBar`.
  - `App.jsx` now handles `lists_update` and `reminders_update` WebSocket
    messages.
- **Tests:** `tests/test_lists.py`.

---

## Phase 4 — Routine Presets & Proactive Notifications ✅ DONE

**Goal:** "Good Morning" / "Good Night" / "Leaving Home" style routines that
combine a Home Assistant scene activation with a guided checklist, plus
proactive (non-voice-triggered) notifications surfaced on-device.

- **Routine Presets** (`units/routine_presets.json`, `core/routines.py`,
  `core/routines_api.py`)
  - `GET /api/vortex/v1/routine/presets` — lists available preset templates
    (name, title, step count, optional scene).
  - `POST /api/vortex/v1/routine/presets/{name}` — activates the preset's
    Home Assistant scene (if any, best-effort) and starts its guided
    routine via the existing `RoutineSession`.
  - Ships with `good_morning`, `good_night`, and `leaving_home` presets;
    edit `units/routine_presets.json` freely per-unit.
- River Song pushes proactive notifications (weather alerts, calendar
  reminders, "you left the garage door open") through the existing
  `notifications_update` channel — no new Vortex API needed.
- **Frontend polish:** `NotificationBar` now shows a default icon per
  priority level (ℹ️/🔔/⚠️/🚨) when a notification doesn't specify its own.
- **Tests:** preset coverage added to `tests/test_routines.py`.

---

## Phase 5 — The Device Layer ✅ DONE

**Goal:** Phases 1–4 built features. This phase built the *device* — the parts
that make a Vortex unit feel like a finished object rather than a browser
pointed at a Pi.

The scaffold's failure mode was not missing modules; it was **broken seams**.
Every subsystem existed and almost nothing was connected: the presenter did not
exist so a screenless unit fired events into nothing, `create_app` never loaded
config on the `--factory` path, the boot screen lost a race with a health
check, the wake word never reached command capture because of a loop it could
not get. Most of this phase was wiring, and most of the bugs were only findable
by running it and looking at the screen.

- **River's presence** (`frontend/src/presence/`)
  - Six states — `idle | listening | thinking | speaking | acting | error` —
    in one contract, ported from River Song's `prototypes/presence-orb.html`.
  - The orb is the first renderer of that contract. The 3D avatar later is a
    second renderer, not a rewrite.
  - Live TTS amplitude rides a ref updated from a rAF loop, so a 30Hz envelope
    triggers zero React re-renders.
  - ⚠️ **Not yet wired.** `AudioManager` tracks `LISTENING → PROCESSING →
    RESPONDING` internally and never broadcasts it; no code sends a `presence`
    or `amplitude` message. The orb therefore only ever shows `idle`. One
    publish call at each state transition closes this.
- **Presenter & voice** (`core/presenter.py`, `core/voice.py`)
  - One image runs a screened Hub and a screenless Mini. The presenter decides
    per-event whether it is shown, spoken, or both.
  - Speech degrades in three tiers: River Song TTS → `espeak-ng` → a chime.
  - Phrase building lives in one place, so every spoken line in the product can
    be reviewed together.
- **Boot self-test** (`core/diagnostics.py`, `pages/Boot.jsx`)
  - 13 real checks, streamed to the screen as each finishes. Nothing on a
    timer, nothing faked. A wall-mounted unit has no keyboard, so this is the
    only place it can say what is wrong.
  - `WARN` boots degraded; only `FAIL` marks the unit unhealthy.
- **Burn-in protection** (`display/screen_manager.py`, `pages/Screensaver.jsx`)
  - active → ambient → drifting screensaver → backlight off, all measured from
    last activity. The final stage cuts `bl_power` rather than setting
    brightness to zero, which is the only version that actually saves the panel.
- **Ambient photos** (`display/photo_library.py`, `core/photos_api.py`)
  - Local-first, so the backdrop survives River Song being down. Two `<img>`
    layers crossfaded on opacity with a transform pan, and the next image
    preloaded, so a slow SD card read never shows as a flash of nothing.
  - Served by name match against the scanned library — no path joining, so no
    traversal.
- **Media playback** (`audio/media_player.py`, `core/media_api.py`)
  - `mpv` as a resident child process over its JSON IPC socket. Transport,
    queue, and ducking that is idempotent, so overlapping timers, routines and
    announcements cannot stack four volume cuts and leave music inaudible.
- **Identity** (`core/config.py`)
  - `unit_id` derived from the Pi serial → MAC → random, because every unit is
    flashed from one image.
  - Name and location stay absent until pairing writes them. A unit in its box
    does not claim to be the kitchen.

---

## Phase 6 — Surfaces: the Context-Aware Screen ✅ DONE (device half)

**Goal:** Make the screen right without being asked — the thing a Nest Hub does
that makes it worth wall-mounting, rather than a clock you occasionally poke.

The design decision is that **Vortex does not decide what is important.**
Knowing that needs the room, the time, who is home and what is cooking, which
only exists on the server. So the unit ships a renderer and a priority queue,
and River Song composes.

- **Surface contract** (`core/surfaces.py`, `frontend/src/surfaces/surfaceContract.js`)
  - Seven card kinds: `note`, `list`, `stat`, `media`, `image`, `alert`,
    `confirm`. Deliberately few — each one is a permanent commitment.
  - Four priorities: `ambient`, `normal`, `high`, `critical`. Priority is
    physical: `high` wakes the panel and speaks aloud even on a screened unit,
    `critical` takes the whole display and cuts playing audio.
  - Upsert by id, so a card that updates itself replaces rather than stacking.
  - Absolute expiry rather than a countdown, so a suspended kiosk does not come
    back with an hour still on the clock. Bounded at 32 cards.
- **Renderer** (`frontend/src/surfaces/Surface.jsx`)
  - Sits beside the clock on the ambient page; `critical` takes over any page.
  - Falls back to clock, weather and photos when nothing is pressing — a hub
    with nothing to say should look deliberate, not blank.
  - Same Pi 4 performance contract as the orb: transform and opacity only.
- **Action relay** (`/api/vortex/v1/surfaces/{id}/action`)
  - Tapping a button sends an opaque intent string to River Song. The unit
    never parses or acts on it, so a `confirm` card on a wall panel is a
    prompt, not a second permission system.
  - The card only comes down once River Song accepts, so a tap that did not
    land does not look like one that did.

**Server half — not built.** The room-aware publisher that decides which unit
gets which card, and `POST /api/vortex/v1/surface-action` for tapped buttons,
both live in River Song.

---

## Phase 7 — Multi-User Voice Personalization (Stretch)

**Goal:** If/when River Song supports per-user voice recognition, let Vortex
reflect *who* it's talking to.

- `POST /api/vortex/v1/session/user` — River Song tags the active session
  with a recognized user ID/name after voice recognition.
- Frontend greets by name ("Good morning, Chris") and can scope
  lists/reminders/timers display per user if desired.

---

## Status Summary

| Phase | Feature | Status |
|---|---|---|
| 1 | WebSocket broadcast hub | ✅ Done |
| 1 | Timers & Alarms | ✅ Done |
| 1 | Guided Routines / Cooking Mode + media ducking | ✅ Done |
| 2 | Multi-room announcements / Drop In | ✅ Done |
| 3 | Lists & reminders display | ✅ Done |
| 4 | Routine presets & proactive notifications | ✅ Done |
| 5 | Presenter, boot self-test, burn-in, photos, media | ✅ Done |
| 5 | Presence orb | ⚠️ Built, not wired — nothing publishes state |
| 6 | Surfaces — context-aware ambient screen | ✅ Done (device half) |
| 7 | Multi-user voice personalization | 🔜 Planned (stretch) |

---

## Blocked on River Song

Vortex's half of each of these is built and tested; the server does not serve
the endpoint yet.

| What River Song owes | Why it matters |
|---|---|
| Constant-time token compare, hashed tokens at rest, lock hard-deny | Foundational. Everything else compounds on it. |
| The unauthenticated device half of pairing | A fresh unit cannot be adopted without it. |
| `/api/vortex/ws` — the persistent uplink | Also the source of the orb's missing amplitude stream. |
| A TTS endpoint | Units currently answer in robotic espeak instead of River's voice. |
| Replica snapshot + deltas | So units stay useful while the server reboots. |
| Weather a unit token can actually fetch | The ambient screen reads "Weather loading…" forever without it. |
| Device / camera / notification feeds | Three headline features are empty screens until this lands. |
| The surface publisher and `/api/vortex/v1/surface-action` | What makes the ambient screen worth wall-mounting. |
| Cooking sessions | So a recipe follows you between rooms. |
| Music resolution that plays on the unit | Today it plays out of whatever the server box is plugged into. |
| Casting | Most likely `pychromecast` via the existing `/api/home` layer. |
| Camera: face matching, video signalling, occupancy, snapshots | The device capture layer is built and waiting. |

## Known Broken Seams

Found by diffing the WebSocket message types the frontend *handles* against
the ones the backend actually *sends*. Every one is the same shape: both
halves written, nothing joining them.

**Fixed:**

- ~~Nothing drives the orb.~~ `AudioManager` now publishes every state
  transition through `_set_state`, which does the assignment and the broadcast
  in one call so the two cannot drift apart again.
- ~~A unit that loses River Song only beeps.~~ It now says
  "I can't reach River Song right now" through the offline voice, skipping the
  server it has just failed to reach rather than stalling on the timeout.

**Still open:**

- **`devices_update` — nothing sends it.** `state.devices` is only ever
  populated by this message, and no backend code emits it. There is also no
  REST endpoint to fetch a device list, and `/api/devices/toggle`, which
  `DeviceGrid` POSTs to, does not exist either. The entire Home Assistant
  device UI renders an empty grid.
- **`cameras_update` — nothing sends it.** Same story; the Cameras page is
  permanently empty.
- **`notifications_update` — nothing sends it.** `NotificationBar` can dismiss
  notifications it can never receive.
- **`amplitude` — nothing sends it.** The orb's `speaking` state is meant to
  pulse with River's voice; nothing measures the envelope of the TTS audio as
  it plays, so `speaking` looks identical to `listening`.
- **`pairing_pin` is broadcast but ignored.** The Setup page fetches the PIN
  over REST instead. Harmless today because the PIN does not rotate, but the
  message is dead weight.
- **The ambient screen has no full-size orb.** Only the 44px corner overlay
  exists, on the screen the unit shows most of the time.

The device/camera/notification group is one decision, not three: they should
be fed by River Song's Home Assistant layer rather than by this repo's
duplicated `home_assistant/` package (see Not Started below).

## Not Started

- **The duplicated `home_assistant/` package** — 824 lines River Song already
  owns. Should be called through, not reimplemented.
- **SoftAP provisioning** — changing WiFi after a house move without
  re-pairing every unit.
- **Pi image work** — hiding the rainbow splash so the self-test is the first
  thing on screen.
- **The 3D avatar** — a second renderer for the existing presence contract.
