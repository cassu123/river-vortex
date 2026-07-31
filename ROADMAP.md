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

## Phase 5 — Multi-User Voice Personalization (Stretch)

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
| 5 | Multi-user voice personalization | 🔜 Planned (stretch) |
