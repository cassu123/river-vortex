# Hardware builds

Each folder is one way to build a River Vortex unit. They all run the **same
software image** — what differs is what is physically in the box, and each
build ships the `vortex_profile.json` that tells the software what it has.

That profile is not documentation. It is read at boot, and it decides what the
unit does: whether the presenter speaks an event or shows it, whether the
settings screen draws a brightness slider, whether the camera layer will open a
lens at all. Copy the profile with the parts list.

## Choosing

| Build | What it is | Screen | Best for |
|---|---|---|---|
| [`hub-7-counter`](hub-7-counter/) | Pi 4 + 7" touchscreen | 800×480 | The one to build first — you already own the Pi |
| [`hub-10-wall`](hub-10-wall/) | Pi 4/5 + 10" touchscreen | 1280×800 | Wall panel, landscape or portrait |
| [`mini-screenless`](mini-screenless/) | Pi Zero 2 W + speaker | none | Voice-only rooms. Cheapest real unit |
| [`satellite-echo-show`](satellite-echo-show/) | Jailbroken Echo Show | 960×480 | ⚠️ Display only — **not** a Vortex unit |
| [`micimike-nest-mini`](micimike-nest-mini/) | ESP32 board in a Nest Mini shell | none | ⚠️ Different software entirely — **not** a Vortex unit |

The last two are in here because they came up and are worth knowing about, but
both are marked because neither runs this codebase. Read their caveats before
buying anything.

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

Create a folder with a `README.md` and a `vortex_profile.json`. The profile
must be a complete, valid profile — the software reads it directly, so a build
sheet whose profile does not load is a build sheet that lies.

Keep `configured: false` and no `unit_id` / `unit_name` / `location`. Identity
is written by pairing; a unit flashed from an image must not claim to be in a
room it has never been installed in, and units flashed from one image must not
share an id.
