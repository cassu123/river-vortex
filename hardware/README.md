# Hardware builds

Each build is one way to assemble a River Vortex unit: a `.md` build sheet and,
where the build runs this software, a matching `.json` unit profile beside it.
They all run the **same software image** — what differs is what is physically
in the box, and the profile is what tells the software what it has.

That profile is not documentation. It is read at boot, and it decides what the
unit does: whether the presenter speaks an event or shows it, whether the
settings screen draws a brightness slider, whether the camera layer will open a
lens at all. Copy the profile with the parts list.

## Choosing

| Build | What it is | Screen | Best for |
|---|---|---|---|
| [`hub-7-counter`](hub-7-counter.md) | Pi 4 + 7" touchscreen | 800×480 | The one to build first — you already own the Pi |
| [`hub-10-wall`](hub-10-wall.md) | Pi 4/5 + 10" touchscreen | 1280×800 | Wall panel, landscape or portrait |
| [`round-spot`](round-spot.md) | Pi 4 + 4" round touch | 720×720 | Bedside or shelf. The orb finally gets round hardware |
| [`mini-screenless`](mini-screenless.md) | Pi Zero 2 W + speaker | none | Voice-only rooms. Cheapest real unit |
| [`satellite-echo-show`](satellite-echo-show.md) | Jailbroken Echo Show | 960×480 | ⚠️ Display only — **not** a Vortex unit |
| [`micimike-nest-mini`](micimike-nest-mini.md) | ESP32 board in a Nest Mini shell | none | ⚠️ Different software entirely — **not** a Vortex unit |

The last two are in here because they came up and are worth knowing about, but
both are marked because neither runs this codebase. Read their caveats before
buying anything.

## Round panels

A round screen is still a **square framebuffer** — the browser cannot tell its
corners are behind a bezel, so a rectangular layout silently loses them.

Set `hardware.screen_shape` to `"round"` and the frontend inscribes itself in
the largest square that fits the circle: side `D/√2`, a 14.65% inset on every
edge. Backgrounds still bleed to the bezel; only content is pulled in. See
`frontend/src/roundScreen.css`.

Every build declares its shape explicitly — `rectangular`, `round`, or `none`
for a screenless unit — rather than relying on a default. A panel that gets
this wrong looks broken in a way that is hard to diagnose from a photo.

## What every build needs

Whatever else changes, a Vortex unit needs:

- **A Linux board that can run Python and Chromium.** No AI accelerator — every
  model runs on the River Song server, which is what keeps a Pi 4 fine.
- **A microphone.** The wake word runs on-device, so the mic is the product.
- **A speaker.** Even a screened unit speaks; a screenless one has nothing else.
- **Wired power.** These are always-on. None of the builds run on battery.
- **WiFi.** No cellular, by design.

## Prices

Every figure in these files is a **rough 2026 ballpark in GBP**, meant for
comparing builds against each other rather than for budgeting. Check current
prices before ordering — Pi pricing in particular has moved a lot.

## Common wiring

Shared across every build that fits them. Pins are BCM numbering and are set in
`core/constants.py` — change them there if they clash with a HAT.

| Pin | Direction | What |
|---|---|---|
| 17 | out | Mic mute LED. **Lit = muted.** |
| 27 | out | Camera active LED. **Lit = camera live.** Opposite of the mic LED on purpose — see below. |
| 22 | in | Physical mic mute switch. Pulled up; closed to ground = muted. |

**Why the two LEDs mean opposite things.** A mic LED answers "am I safe to
talk?", so it lights when muted. A camera LED answers "is it looking at me
right now?", so it lights when active. Getting that backwards on a bedroom
panel means a dark LED over a live lens.

**The mute switch is authoritative.** While it is closed, software cannot
unmute — not the touchscreen, not River Song, not a voice command. Wire a
latching SPST switch between pin 22 and ground.

For the strongest version, wire the switch to **break the microphone's power or
data line as well**, and let pin 22 only tell the software what already
happened. Both wirings work with the code; only that one survives a compromised
Pi. It is the difference between a promise the software keeps and a promise the
hardware keeps.

## Adding a build

Add `<build-name>.md` here, and `<build-name>.json` beside it if the build runs
this software. Add a row to the table above. Flat on purpose — a folder per
build buys nothing and buries the thing you actually want to read.

The profile must be complete and valid, because the software reads it directly:
a build sheet whose profile does not load is a build sheet that lies. Register
the name in `BUILDS` in `tests/test_hardware_profiles.py` and the tests will
hold it to its own parts list.

Keep `configured: false` and no `unit_id` / `unit_name` / `location`. Identity
is written by pairing; a unit flashed from an image must not claim a room it
was never installed in, and units flashed from one image must not share an id.

A build that **cannot** run this software ships no `.json`. A profile there
would invite someone to copy it onto hardware that will never boot it.
