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

## Phase 2 — Multi-Room Audio & Announcements ("Drop In")

**Goal:** "Announce to all rooms" and "Drop In" on a specific room, the way
Alexa/Google Home broadcast across a household.

- `POST /api/vortex/v1/announce` — Vortex receives a TTS audio clip (or text
  for local synthesis) from River Song and plays it immediately, ducking
  media first (reuse the Phase 1 ducking helper).
- Extend `intercom/intercom_manager.py` so a "Drop In" request opens a live
  two-way audio channel to a specific unit, with an on-screen incoming-call
  banner (reusing the `notification` display mode).
- Broadcast `announcement` / `intercom_incoming` events over `/api/ws` so the
  frontend can show "📢 Announcement" / "📞 Drop In from Kitchen" overlays.

---

## Phase 3 — Lists & Reminders Display Surface

**Goal:** Shopping lists, to-do lists, and reminders visible and
checkable/snoozable from the touchscreen — data is owned by River Song,
Vortex just displays the latest snapshot and relays touch actions.

- `GET /api/vortex/v1/lists`, `POST /api/vortex/v1/lists/{list_id}/items/{item_id}/toggle`
  — thin pass-through that Vortex caches locally for instant display and
  forwards to River Song for persistence.
- `reminders_update` WebSocket event — upcoming reminder banner via the
  existing notification overlay.
- New `Lists` page in the frontend (checklist UI, similar styling to
  `Routine`).

---

## Phase 4 — Routine Presets & Proactive Notifications

**Goal:** "Good Morning" / "Good Night" / "Leaving Home" style routines that
combine a Home Assistant scene activation with a guided checklist, plus
proactive (non-voice-triggered) notifications surfaced on-device.

- Preset routine templates stored alongside `units/vortex_profile.json`,
  triggerable via `/api/vortex/v1/routine/presets/{name}`.
- River Song pushes proactive notifications (weather alerts, calendar
  reminders, "you left the garage door open") through the existing
  `notifications_update` channel — no new Vortex API needed, just
  documentation + frontend polish for priority styling.

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
| 2 | Multi-room announcements / Drop In | 🔜 Planned |
| 3 | Lists & reminders display | 🔜 Planned |
| 4 | Routine presets & proactive notifications | 🔜 Planned |
| 5 | Multi-user voice personalization | 🔜 Planned (stretch) |
