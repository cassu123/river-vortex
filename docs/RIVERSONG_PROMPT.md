# RiverSongAI prompt — the server half of River Vortex

Paste everything below the `---` into a session against `cassu123/RiverSongAI`.

This is the complete server-side counterpart to the River Vortex device layer.
The device half is built, tested and merged; every endpoint described here as
"the unit already calls this" genuinely exists and genuinely has no server to
talk to.

Written against RiverSongAI at commit `f918c2b`. Line numbers are hints, not
guarantees — verify before trusting them, and adapt if the code has moved.

---

# River Vortex — server-side implementation brief

## What you are building

River Vortex is the physical device layer of this ecosystem: Raspberry Pi
smart displays and screenless speakers, one per room. They are **thin
clients**. No model runs on them, they do no intent recognition, and they hold
no privileged credentials.

Everything that requires knowing something — what the user meant, who is
speaking, what deserves the screen, whether an action is permitted — happens
here. The units render and they listen; this server decides.

Your job is to build the half of that contract this server does not yet
implement. The device half is finished, so most of this is "something is
already calling you and getting a 404."

---

## Read before writing anything

Do not rebuild these. Extend them.

| Where | What it already does |
|---|---|
| `api/routes/fleet.py` | `build_fleet_router()` generates a router per program; `FLEET_PROGRAMS` (~line 50) already includes `"vortex"`. Surface: `/register`, `/heartbeat`, `/telemetry`, `/alerts`, `GET /commands` (poll), `/commands/{id}/ack`. Per-unit `X-Unit-Token`; `_verify_unit()` ~line 114. |
| `api/routes/willow.py` | The existing voice WebSocket. **Copy its auth shape** — refuse before `accept()`, require an auth frame first. **Do not copy its credential model**: it uses one shared device token and lets the client self-assert `user_id`. |
| `api/routes/culinary.py` | Recipes, scaling, `translate-equipment`, banned ingredients, dinner proposals. `cook_now` (~line 1467) returns `{recipe_id, title, servings, shopping_list, steps}`. Household WebSocket ~line 895 with a `_ws_manager`. |
| `config/settings.py` (~line 737) | `wake_word_enabled`, `wake_word_model`, `wake_word_threshold`. **openWakeWord**, not Porcupine. |
| `providers/smart_home/home_assistant.py`, `/api/home/*` | Home Assistant lives here. Units must never hold HA credentials. |
| `providers/google/youtube_music.py` | A working player wired to the wrong speaker — see Task 3b. |
| `core/intent_router.py` | Where permission decisions belong. |
| `core/fleet_simulator.py` (~line 190) | Already accepts `cast` / `stop_cast` for vortex units and tracks `cast_target`. Neither side implements them. |

---

## Invariants

These are not preferences. Breaking any of them breaks the security model, and
the device layer is built assuming they hold.

1. **A unit never decides permission.** Not for a voice command, not for a
   tapped button, not for a recognised face. The unit relays; you decide.

2. **Locks, garage doors and alarm disarm are hard-denied to Vortex units** —
   refused at the intent router because the request came from a unit, not
   merely gated behind a confirmation. A Pi stolen from a kitchen must not be
   able to open a door. The owner asked for this explicitly.

3. **Units never hold Home Assistant credentials.** All device state and all
   device control flows through `/api/home/*`.

4. **A unit never self-asserts identity.** It sends frames and audio; you
   return who it is. Never accept a `user_id` from a unit.

5. **Second factors are entered on the touchscreen, never spoken.** A spoken
   PIN travels the same channel as the voice that triggered it and is audible
   to the whole room, so it adds no factor at all.

6. **Camera consent is per purpose and lives on the unit.** You may request a
   capture; the unit refuses purposes its owner has not enabled. Never treat a
   refusal as a fault to route around.

7. **Anything pushed to a screenless unit must carry `speech`** or it is
   invisible. Roughly a third of units have no display.

---

## Dependency order

Build in this order. Later tasks assume earlier ones.

```
Task 5  (security)          ─┐
Task 4  (pairing)           ─┼─→ foundational, nothing works properly without them
Task 1  (WebSocket)         ─┘
                              │
Task 2  (replica)  ───────────┼─→ Task 1b (weather rides on replica)
Task 7  (HA feeds) ───────────┘
                              │
Task 6  (surfaces) ───────────┼─→ Task 8 (camera) needs surfaces for motion cards
Task 3  (cooking)             │
Task 3b (music)               │
Task 3c (casting)             │
Task 9  (TTS)                 │
```

If you can only do three things: **Task 5, Task 1, Task 6.** Security first,
then the channel, then the thing that makes the screens worth having.

---

## Task 5 — Security fixes

Do these first. They are small and everything else compounds on them.

- `fleet.py` (~line 122) and willow's auth both compare tokens with `!=`.
  Use `hmac.compare_digest`.
- `unit_token` is stored in plaintext in `fleet_units`. Hash at rest; compare
  against the hash.
- Add the hard deny in `core/intent_router.py` for lock, garage and
  alarm-disarm domains when the request originates from a vortex unit. See
  invariant 2.
- Medium-risk actions return `pending_confirmation` with a challenge id rather
  than executing. The device collects the second factor and returns it against
  that id; hold the pending state with a short TTL.

**Done when:** a unit token cannot be timing-attacked, the database contains no
plaintext unit tokens, and a unit asking to unlock a door is refused at the
router with a log line saying why.

---

## Task 4 — Pairing

Fresh units have no token. `POST /api/vortex/units/claim` exists but is
admin-only; build the unauthenticated device half.

- `POST /api/vortex/pair/request` — unit posts a self-generated 8-digit code
  plus its metadata. Store pending with a 10-minute TTL.
- `GET /api/vortex/pair/status?code=` — unit polls; returns `unit_id` and token
  once approved, **exactly once**.
- `POST /api/vortex/pair/approve` — **authenticated user only**. Approves a
  code and mints the unit.

The code alone must never mint a token. Rate-limit and lock out both
`pair/status` and `pair/approve` — 8 digits is 10⁸ and otherwise brute
forceable. Units poll outbound; the app never connects inbound to a Pi.

**Done when:** a factory-reset unit can be adopted end to end by a logged-in
user, and a script hammering `pair/status` gets locked out.

---

## Task 1 — `/api/vortex/ws`

One authenticated bidirectional channel per unit. Polling cannot carry
presence: River highlighting a card *while she talks about it* needs sub-second
latency. Keep the existing `/commands` poll for slow, offline-tolerant
operations (`restart`, `run_scene`).

**Auth:** refuse before `accept()` if the unit is unknown. First frame must be
`{"type":"auth","unit_id":…,"token":…}`, validated the same way
`_verify_unit()` does, with `hmac.compare_digest`. Drop the socket if no valid
auth frame arrives within 5 seconds.

**Unit → server**

| Type | Payload |
|---|---|
| `audio_chunk` | base64 PCM, 16kHz mono s16le. Sent only after local wake word confirmation. |
| `state` | The unit's own presence state. |
| `ack` | Command acknowledgement. |
| `occupancy` | Presence sensor / camera occupancy — see Task 8. |

**Server → unit**

| Type | Payload |
|---|---|
| `presence` | `{state, amplitude, mood, caption}`. State ∈ `idle\|listening\|thinking\|speaking\|acting\|error`. **This vocabulary is fixed** — it comes from `prototypes/presence-orb.html` and the Vortex orb consumes exactly this object. |
| `amplitude` | `{value: 0..1}` at ~30Hz while TTS plays, derived from the Piper output envelope. |
| `audio` | base64 TTS response. |
| `surface` | Card descriptor — Task 6. |
| `navigate` | `{page}`. |
| `replica` | State deltas — Task 2. |

**Note on `amplitude`:** the unit's orb has a full renderer for this and
nothing currently drives it, so River's "speaking" state does not pulse. It is
the single highest-impact cosmetic fix in the system, and it can only come from
here — the unit plays an opaque audio blob and cannot measure it meaningfully.

**Done when:** a unit connects, authenticates, and its orb visibly tracks
River's voice while she speaks.

---

## Task 2 — Replica snapshot and deltas

Units render from a local copy so the UI never blocks on the network and stays
useful while this server reboots. They have no cellular — when WiFi drops they
are fully offline.

- `GET /api/vortex/replica?since=<version>` — devices, rooms, the household's
  wake word phrase, and unit settings. With `since`, return only what changed
  plus a new version stamp.
- Push `replica` deltas over the WebSocket as state changes.
- Source device and room data from `/api/home`. See invariant 3.

---

## Task 1b — Weather for units

`/api/feeds/weather` (`api/routes/feeds.py` ~line 152) already returns weather
but authenticates a **user** via `_require_user(authorization)`. A unit holds a
unit token, not a user JWT, so it cannot call it. **The ambient screen on every
unit currently reads "Weather loading…" forever.**

Either accept a unit token on that route and resolve it to the household's
user, or include a `weather` block in the replica payload. **Prefer the
replica route** — units already need it, and it means weather survives the
server being briefly unreachable.

Include `weather/alerts`. A wall panel is exactly the right place for a severe
weather warning, and it should arrive as a `high` priority surface.

---

## Task 7 — Home Assistant device, camera and notification feeds

**New, and larger than it looks.** The Vortex device grid, camera page and
notification bar are all built and all render from state that nothing
populates. There is no REST endpoint and no push. Three of the README's
headline features are, today, empty screens.

The units listen for these WebSocket messages and nothing sends them:

- `devices_update` — `{data: [...]}`, the household's controllable entities
- `cameras_update` — `{data: [...]}`, HA camera entities with snapshot URLs
- `notifications_update` — `{data: [...]}`, active notifications

They also POST to `/api/devices/toggle` on their own backend, which does not
exist on either side.

Build this **here**, sourced from `/api/home`, and push over `/api/vortex/ws`
or fold into the replica payload from Task 2 — the replica is the better home,
since device state is exactly the thing a unit should keep a local copy of.

The device layer deliberately did *not* build this against its own bundled
`home_assistant/` package: that package duplicates ~800 lines this server
already owns, and giving units a second path to HA would break invariant 3.
Expect that package to be deleted once this task lands.

Include a control path too — `toggle`, `set_brightness`, `set_temperature`,
`open`/`close` — routed through the intent router so the Task 5 hard-deny
applies to a tapped light switch exactly as it does to a spoken one.

---

## Task 6 — Surfaces: decide what the ambient screen shows

Vortex has a complete surface renderer and holds **no opinion** about what
deserves the screen. It draws seven card shapes and orders them by a priority
it is handed. Deciding what matters right now needs the room, the time, who is
home and what is cooking — context that only exists here.

The unit's half is done and live:

- `POST /api/vortex/v1/surfaces` — show or replace a card
- `DELETE /api/vortex/v1/surfaces/{id}` — withdraw it
- `GET /api/vortex/v1/surfaces` — current cards (the kiosk reads this on restart)

```jsonc
{
  "id": "garage",          // stable — pushing the same id REPLACES, never stacks
  "kind": "alert",         // note | list | stat | media | image | alert | confirm
  "priority": "high",      // ambient | normal | high | critical
  "title": "Garage door still open",
  "body": "It's been open for 40 minutes.",
  "value": "4", "unit": "°C",           // stat only
  "items": ["Milk", "Coffee"],           // list only, max 8
  "image_url": "...", "icon": "⚠",
  "actions": [{"label": "Close it", "intent": "cover.close.garage",
               "style": "primary"}],     // max 3
  "ttl_seconds": 900,
  "speech": "The garage has been open for forty minutes."
}
```

**Priority is physical, not decorative.** The unit enforces this, so choose
deliberately:

| Priority | What the unit does |
|---|---|
| `ambient` | Idle filler. Shown only when nothing else wants the screen. |
| `normal` | Sits beside the clock. |
| `high` | **Wakes the panel from backlight-off and speaks aloud even on a unit that has a screen.** |
| `critical` | All of the above, plus takes over the whole display over any page and cuts off playing audio. |

`high` and `critical` are physical interruptions in a bedroom at 3am. Doorbells,
smoke, water. Not deliveries.

**Build:**

1. **A room-aware publisher.** The shopping list belongs on the kitchen unit,
   not the bedroom one.
2. **Withdrawal when the fact stops being true.** A card left to expire is a
   card that stayed up after it stopped mattering.
3. **`POST /api/vortex/v1/surface-action`** — *this does not exist and Vortex
   already calls it.* Body `{surface_id, intent, unit_id}`. The unit relays the
   tapped button verbatim and never interprets it. Re-run the intent through
   `core/intent_router.py` with the same checks as a voice command, including
   the Task 5 hard-deny — a confirm card on a wall panel is a prompt, not an
   authorisation. Return 2xx only when accepted; the unit leaves the card up on
   anything else, so a tap that did not land never looks like one that did.

**Worth building early, because it is what makes the product feel alive:**
bin day the night before, garage still open, someone at the door, the parcel
that arrived, "you left the hob on." Each is a few lines here and requires
nothing further on the device.

---

## Task 3 — Cooking sessions

The biggest single feature. `cook_now` returns steps and forgets — nothing
tracks "we are on step 3." Sessions are household-scoped so the kitchen Vortex,
a phone and the browser all show the same step, and a Pi reboot mid-recipe does
not lose your place.

- `POST /api/culinary/sessions` — start from a recipe id with target servings.
  Apply the existing scaling and equipment-translation logic.
- `GET /api/culinary/sessions/current`
- `POST /api/culinary/sessions/{id}/step` — `{action: next|back|goto, index?}`
- `POST /api/culinary/sessions/{id}/timer` — named timers bound to a step,
  surviving reboot. **Persist the wall-clock deadline, not a countdown.**
- `POST /api/culinary/sessions/{id}/end`
- Broadcast every change over both the culinary WS and `/api/vortex/ws`.

Each step carries: index, total, instruction text, the ingredients for *that
step only*, and any timer the step implies.

The canonical step field is **`instruction`**. The device reads that, with
`text` as a tolerated alias — a mismatch here leaves River silent on every step
of a recipe, which on a screenless unit is the entire feature.

Voice intents to route while a session is active: next, back, repeat, "how much
`<ingredient>`", "set a timer for N", "how long left".

---

## Task 3b — Music must play on the unit, not on the server

`providers/google/youtube_music.py` plays audio **on the River Song box
itself** — it has an `audio_output_device` and a `_download_and_play`, and
`_handle_youtube_music` (`core/intent_router.py` ~line 424) calls
`play_first_result()`. Asking for music in the kitchen plays it out of whatever
the server is plugged into.

Split resolve from playback:

- Add a resolve-only path returning `{url, title, artist, album, artwork_url,
  duration_seconds}` plus an optional queue, playing nothing locally. The URL
  must be a direct stream URL the unit can fetch.
- When a play intent arrives from a unit, POST that payload to that unit's
  `POST /api/vortex/v1/media/play` (already implemented) or push it over the
  WebSocket. Keep local playback only for requests that did not come from a
  unit.
- Route transport intents — pause, resume, skip, previous, stop, louder — to
  the same unit's `/api/vortex/v1/media/*`.
- "Play it in the living room" resolves a room to a unit_id and targets that
  unit instead of the one that heard the request.

The device side needs nothing from you but a URL. Transport, queue, volume and
ducking all work, and the unit ducks its own music while River speaks.

---

## Task 3c — Casting

`core/fleet_simulator.py` (~line 190) accepts `cast` / `stop_cast` and tracks a
`cast_target`; neither side implements them.

There is no official Google Cast REST API. The practical route is
`pychromecast` — which is what Home Assistant already uses — so casting most
likely means handing a stream to an HA `media_player` entity through
`/api/home` rather than doing anything on the Pi. Decide the command payload;
Vortex will need a matching handler and has none today.

YouTube *video* casting specifically is reverse-engineered and fragile. Treat
it as out of scope unless you want to own that maintenance.

---

## Task 9 — TTS endpoint

`core/voice.py` on the device does `getattr(client, "synthesize_speech", None)`
and falls through to offline espeak-ng when it is absent — which is always,
because this server has no such endpoint. **Every unit in the house currently
speaks in a robotic offline voice**, not River's.

Add a synthesis endpoint a unit token can call, returning WAV bytes for a given
string. Same Piper path the rest of the system uses.

While you are there: emit the `amplitude` stream from Task 1 off the same
synthesis, since you have the envelope in hand at exactly that moment.

---

## Task 8 — Cameras

**New.** Screened units are getting cameras. The device layer for this landed
already, built privacy-first, and it constrains what you can do here.

### What the unit enforces, regardless of what you ask

- A camera is **not fitted** unless that unit's profile says so.
- Each use is consented **separately**: `video_calls`, `motion_snapshots`,
  `presence`, `face_recognition`. All default off.
- A capture request for a purpose the owner has not enabled is **refused**, and
  refusal is a distinct error from hardware failure. Do not retry around it.
- The privacy LED is an interlock driven by the capture session itself. Frames
  are impossible without the light being on. There is no override, and you
  should not ask for one.

The unit reports its camera state — fitted, available, active, muted, and each
purpose flag — so you can know what is possible before requesting it.

### What to build here

**a) Face recognition as a second factor.** This is the owner's original
request and is now possible. The unit uploads frames; **this server decides who
it is** (invariant 4). Combine with the on-screen PIN from Task 5 for genuine
two-factor on medium-risk actions. The unit must never receive a roster of
faces or an embedding database — it sends pixels and gets back a decision.

Note this still does not unlock doors. Invariant 2 stands regardless of how
confidently a face is matched.

**b) Video calls.** Extend the existing room-to-room intercom from audio to
video. Signalling belongs here; the media path should stay peer-to-peer on the
LAN. Phone-to-house via the River Song app should use the same path.

**c) Occupancy.** Units will report `occupancy` over the WebSocket, sourced
from the camera and/or an optional mmWave sensor. Use it to route music and
calls to the room the user is actually in — "follow-me audio" — and to wake
the right screen. Treat it as a hint, never as an authorisation signal.

**d) Motion snapshots.** Accept snapshots and expose the unit as a camera
entity in Home Assistant, alongside the household's existing cameras. Motion
should raise a `high` surface with the snapshot as `image_url`, and a doorbell
should raise a `critical` one — which is the takeover case the surface renderer
was built around.

**Retention is your decision to make explicitly.** These are cameras in
bedrooms. Decide how long snapshots live, say so in the code, and default to
short.

---

## Anti-goals

Do not:

- Give units Home Assistant credentials, or any path to HA that bypasses
  `/api/home`.
- Accept a `user_id`, a role, or an identity claim from a unit.
- Let a unit's confirmation UI stand in for a server-side permission check.
- Add intent recognition, wake word logic, or model inference to the device
  side. It has none and should keep none.
- Build a second surface priority model here. The unit's four levels are the
  contract; pick from them.
- "Fix" a camera consent refusal by finding another way to get the frame.

---

## Verifying you are done

Per task, the observable result:

| Task | You have finished when |
|---|---|
| 5 | No plaintext unit tokens in the database; a unit asking to unlock a door is refused at the router. |
| 4 | A factory-reset unit is adopted end to end by a logged-in user; brute-forcing the code gets locked out. |
| 1 | A unit authenticates and its orb tracks River's voice as she speaks. |
| 2 / 7 | Unplug this server; the unit's clock, device grid and photos keep working. |
| 1b | The ambient screen shows real weather instead of "Weather loading…". |
| 6 | Say "remind me about the bins" and a card appears on the kitchen unit and nowhere else. |
| 3 | Start a recipe on the browser, walk to the kitchen, and the Vortex is on the same step. |
| 3b | Ask for music in the kitchen and it comes out of the kitchen. |
| 9 | A unit answers in River's voice, not espeak's. |
| 8 | Someone at the door raises a full-screen card with their picture on every screen in the house. |

## Context you may want

The Vortex repo is `cassu123/river-vortex`. Its `README.md` documents every
device endpoint referenced here, and `ROADMAP.md` tracks what is built versus
blocked. Both are kept honest — features that are UI-only are labelled as such
rather than claimed.
