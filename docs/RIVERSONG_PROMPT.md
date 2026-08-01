# RiverSongAI prompt — Vortex channel + cooking sessions

Paste the block below into a session against `cassu123/RiverSongAI`. It is the
server half of the Vortex work; the Vortex half lives in this repo.

Written against RiverSongAI at commit `f918c2b`. Check these still hold before
starting — if they have moved, adapt rather than assuming.

---

## Prompt

You are adding two things to RiverSongAI: a realtime channel for River Vortex
hub units, and cooking sessions. Vortex units are Raspberry Pi touchscreens in
each room — they are thin clients, all intelligence stays here.

### Context that already exists — read before writing anything

- `api/routes/fleet.py` — `build_fleet_router()` generates an identical router
  per program. `FLEET_PROGRAMS` at line 50 already includes `"vortex"`. Device
  surface: `/register`, `/heartbeat`, `/telemetry`, `/alerts`,
  `GET /commands` (poll), `/commands/{id}/ack`. Units authenticate with a
  per-unit `X-Unit-Token`; `_verify_unit()` is at line 114.
- `api/routes/willow.py` — the existing voice WebSocket. Copy its auth shape
  (refuse before `accept()` when unconfigured, require an auth frame first)
  but NOT its credential model: it uses one shared device token and lets the
  client self-assert `user_id`. Vortex must use per-unit tokens instead.
- `api/routes/culinary.py` — recipes, scaling, `translate-equipment`, banned
  ingredients, dinner proposals. `cook_now` (line 1467) already returns
  `{recipe_id, title, servings, shopping_list, steps}`. There is a
  household-scoped WebSocket at line 895 and a `_ws_manager` for broadcast.
- `config/settings.py:737` — `wake_word_enabled`, `wake_word_model` (the
  phrase), `wake_word_threshold`. openWakeWord, not Porcupine.
- `providers/smart_home/home_assistant.py` and `/api/home/*` — Home Assistant
  already lives here. Vortex must NOT talk to Home Assistant directly.

### Task 1 — `/api/vortex/ws`

A single authenticated bidirectional channel per unit. Polling cannot carry
presence: River highlighting a device card *while she talks about it* needs
sub-second latency. Keep the existing `/commands` poll for slow operations
(`restart`, `run_scene`) — it is the offline-tolerant path.

Auth: refuse before `accept()` if the unit is unknown. First frame must be
`{"type":"auth","unit_id":...,"token":...}`, validated against `fleet_units`
via the same path `_verify_unit()` uses. Drop the socket if no valid auth
frame arrives within 5 seconds. Use `hmac.compare_digest` for the comparison.

Unit to server:
- `audio_chunk` — base64 PCM, 16kHz mono s16le, sent only after local wake
  word confirmation
- `state` — the unit's own presence state
- `ack` — command acknowledgement

Server to unit:
- `presence` — `{state, amplitude, mood, caption}` where state is one of
  `idle|listening|thinking|speaking|acting|error`. This vocabulary is fixed;
  it comes from `prototypes/presence-orb.html` and the Vortex orb already
  consumes exactly this object.
- `amplitude` — `{value: 0..1}` at ~30Hz while TTS plays, so the orb tracks
  River's voice. Derive it from the Piper output envelope.
- `audio` — base64 TTS response
- `surface` — declarative UI descriptor (see Task 3)
- `navigate` — `{page}`
- `replica` — state deltas (see Task 2)

### Task 1b — weather for units

`/api/feeds/weather` (`api/routes/feeds.py:152`) already returns weather, but
it authenticates a USER via `_require_user(authorization)`. A Vortex unit
holds a unit token, not a user JWT, so it cannot call it — the ambient screen
currently has no weather at all.

Expose the same data to units: either accept a unit token on the feeds
weather route and resolve it to the household's user, or include a `weather`
block in the replica payload below and push updates over `/api/vortex/ws`.
The replica route is cleaner — units already need it, and it means weather
survives the server being briefly unreachable.

Include `weather/alerts` too; a wall panel is the right place for a severe
weather warning.

### Task 2 — replica snapshot and deltas

Units render from a local copy so the UI never blocks on the network and
stays useful when this server is down or rebooting. They have no cellular —
when wifi drops they are fully offline.

- `GET /api/vortex/replica?since=<version>` — returns devices, rooms, the
  household's wake word phrase, and unit settings. With `since`, return only
  what changed plus a new version stamp.
- Push `replica` deltas over the WebSocket as state changes.
- Source device and room data from the existing `/api/home` layer. Do not
  give units Home Assistant credentials.

### Task 3 — cooking sessions

The biggest feature. `cook_now` returns steps and forgets — nothing tracks
"we are on step 3". Sessions are household-scoped so the kitchen Vortex, a
phone, and the browser all show the same step, and a Pi reboot mid-recipe
does not lose your place.

- `POST /api/culinary/sessions` — start from a recipe id, with target
  servings. Apply the existing scaling and equipment-translation logic.
- `GET /api/culinary/sessions/current`
- `POST /api/culinary/sessions/{id}/step` — `{action: next|back|goto, index?}`
- `POST /api/culinary/sessions/{id}/timer` — named timers bound to a step,
  surviving reboot (persist the wall-clock deadline, not a countdown)
- `POST /api/culinary/sessions/{id}/end`
- Broadcast every change over both the culinary WS and `/api/vortex/ws`.

Each step should carry: index, total, instruction text, the ingredients for
*that step only*, and any timer the step implies.

Voice intents to route while a session is active: next, back, repeat, "how
much <ingredient>", "set a timer for N", "how long left".

### Task 3b — music must play on the unit, not on the server

`providers/google/youtube_music.py` currently plays audio **on the River Song
box itself** — it has an `audio_output_device` and a `_download_and_play`, and
`_handle_youtube_music` (`core/intent_router.py:424`) calls
`play_first_result()`. So asking for music in the kitchen plays it out of
whatever the server is plugged into. It is a working player wired to the wrong
speaker.

Split resolve from playback:

- Add a resolve-only path that returns `{url, title, artist, album,
  artwork_url, duration_seconds}` plus an optional queue, without playing
  anything locally. The URL must be a direct stream URL the unit can fetch.
- When a play intent arrives from a Vortex unit, POST that payload to the
  unit's own `POST /api/vortex/v1/media/play` (already implemented on the
  device), or push it over `/api/vortex/ws`. Keep local playback only for
  requests that did not come from a unit.
- Route transport intents — pause, resume, skip, previous, stop, "louder" —
  to the same unit's `/api/vortex/v1/media/*` endpoints.
- "Play it in the living room" targets a different unit: resolve the room to a
  unit_id and send it there instead of the one that heard the request.

The device side is done and needs nothing from you beyond being handed a URL:
transport, queue, volume and ducking all work, and the unit ducks its own
music automatically while River speaks or an announcement plays.

### Task 3c — casting

`core/fleet_simulator.py:190` already accepts `cast` and `stop_cast` for
vortex units and tracks a `cast_target`, but neither side implements them.
Decide what casting means here — most likely handing the stream to a Home
Assistant `media_player` entity via the existing `/api/home` layer rather than
anything on the Pi — and then define the command payload. Vortex will need a
matching handler; it has none today.

### Task 4 — pairing

Fresh units have no token. `POST /api/vortex/units/claim` exists but is
admin-only; add the unauthenticated device half.

- `POST /api/vortex/pair/request` — unit posts a self-generated 8-digit code
  and its metadata; server stores it pending with a 10 minute TTL
- `GET /api/vortex/pair/status?code=` — unit polls; returns its unit_id and
  token once approved, exactly once
- `POST /api/vortex/pair/approve` — **authenticated user only**, approves a
  code and mints the unit

The code alone must never mint a token — approval requires a logged-in user.
Rate limit and lock out `pair/status` and `pair/approve`: 8 digits is only
10^8 and is otherwise brute-forceable. Units poll, the app never connects
inbound to the Pi.

### Task 6 — surfaces: decide what the ambient screen shows

Vortex now has a **surface renderer** and holds no opinion about what deserves
the screen. It draws seven card shapes and orders them by a priority it was
given. Deciding *what matters right now* needs the whole house's context —
the room, the time, who is home, what is cooking — which only lives here.

The unit already implements its half:

- `POST /api/vortex/v1/surfaces` — show or replace a card
- `DELETE /api/vortex/v1/surfaces/{id}` — withdraw it
- `GET /api/vortex/v1/surfaces` — current cards (kiosk reads this on restart)

Card body:

```json
{
  "id": "garage",          // stable — pushing the same id REPLACES, never stacks
  "kind": "alert",         // note | list | stat | media | image | alert | confirm
  "priority": "high",      // ambient | normal | high | critical
  "title": "Garage door still open",
  "body": "It's been open for 40 minutes.",
  "value": "4", "unit": "°C",          // stat only
  "items": ["Milk", "Coffee"],          // list only, max 8
  "image_url": "...", "icon": "⚠",
  "actions": [{"label": "Close it", "intent": "cover.close.garage",
               "style": "primary"}],    // max 3
  "ttl_seconds": 900,
  "speech": "The garage has been open for forty minutes."
}
```

Priority semantics the unit enforces, so pick deliberately:

- `ambient` — idle filler, shown only when nothing else wants the screen
- `normal` — sits beside the clock
- `high` — **wakes the screen from screensaver/backlight-off, and is spoken
  aloud even on a unit that has a display**
- `critical` — all of the above, plus takes over the whole panel and cuts off
  whatever audio is playing

`high` and `critical` are physical interruptions in a bedroom at 3am. They are
for doorbells, smoke and water, not for a delivery notification.

`speech` is what carries the card to a **screenless Mini**, which has no other
way to receive it at all. A card with no `speech` is invisible on a Mini.

What to build here:

1. A surface publisher that pushes to the right units. Room-aware: the
   shopping list belongs on the kitchen unit, not the bedroom one.
2. Withdrawal when the fact stops being true. A card left to expire is a card
   that stayed on screen after it stopped mattering.
3. `POST /api/vortex/v1/surface-action` — **this endpoint does not exist yet
   and Vortex already calls it.** Body: `{"surface_id", "intent", "unit_id"}`.
   Vortex relays the tapped button verbatim and never interprets it. Re-run
   the intent through `core/intent_router.py` with the same permission checks
   as a voice command, including the Task 5 lock hard-deny — a confirm card on
   a wall panel is a prompt, not an authorisation. Return 2xx only when the
   action is accepted; the unit leaves the card up on anything else, so a tap
   that did not land does not look like one that did.

### Task 5 — security fixes in passing

- `fleet.py:122` and willow's auth both compare tokens with `!=`. Use
  `hmac.compare_digest`.
- `unit_token` is stored in plaintext in `fleet_units`. Hash at rest and
  compare against the hash.
- Vortex units must be **hard-denied** the lock, garage and alarm-disarm
  domains in `core/intent_router.py`, keyed on the request originating from a
  vortex unit — not merely gated behind confirmation. Enforced here, never on
  the device: a stolen Pi from the kitchen must not be able to open a door.
- Medium-risk actions return `pending_confirmation` with a challenge id
  rather than executing. The device collects the second factor and returns it
  against that id; the server holds the pending state with a short TTL.
  Second factor is a PIN entered **on the touchscreen**, not spoken — a
  spoken PIN travels the same channel as the voice that triggered it and is
  audible to the room, so it adds no real factor.

### Out of scope

Face recognition. Vortex units have no camera in the hardware spec.
