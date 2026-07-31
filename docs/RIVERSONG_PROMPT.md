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
