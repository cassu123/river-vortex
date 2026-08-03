# Mini — screenless

Voice only. No screen, no touch — a speaker that listens. For rooms where a
panel would be daft: a hallway, a garage, a bedside table.

The cheapest real Vortex unit, and the one that proves the architecture: it
runs the **same image** as a 10" wall panel and behaves correctly without a
display, because `core/presenter.py` speaks anything the screen would have
shown.

## Parts

| Part | Notes | ~GBP |
|---|---|---|
| Raspberry Pi Zero 2 W | Quad core, 512MB. Enough — there is no browser on this build | 18 |
| PSU 5V 2.5A micro-USB | | 8 |
| microSD 16GB A2 | | 6 |
| ReSpeaker 2-Mic HAT | Fits the Zero form factor | 15 |
| MAX98357A I2S amp + 3W speaker | I2S rather than the Zero's audio, which is genuinely poor | 10 |
| Small enclosure | 3D printed or a project box | 5–15 |
| Latching SPST switch | Mute. **Especially worth it on this build** — a device with no screen has no other way to show it is listening | 3 |
| 3mm LED + 330Ω resistor | Mic mute indicator | 1 |

**~£65–80.**

## Why the mute switch matters more here

On a screened unit you can glance at the panel and see the "Microphone muted"
bar. This build has no panel. The LED **is** the interface for that, and the
switch is the only way to be sure.

The software knows: an error River Song reports as a presence caption gets
**spoken aloud** on a screenless unit rather than sent to a browser that does
not exist. That path exists specifically because a Mini that fails silently is
a Mini nobody can debug.

## Memory

512MB is the constraint. It is fine because this build runs no browser — but
do not enable ambient photos (there is no screen to put them on) and do not
add other services to the box.

The shipped profile sets `ambient_mode_enabled: false` for exactly that reason.

## What it can and cannot do

**Can:** wake word, voice commands, River's replies, timers, cooking mode
step-by-step, announcements, intercom, music playback, surface cards read
aloud.

**Cannot:** anything visual. A surface card with no `speech` field is invisible
on this unit — River Song derives speech from the card text when it can, but a
card that is genuinely a photo is a card this unit will not deliver.

## Wiring

Standard pins, see [shared wiring](../README.md#common-wiring). No camera LED
needed — there is no camera on this build and the profile says so.

## Software

```bash
cp hardware/mini-screenless/vortex_profile.json units/vortex_profile.json
```

The important line is `"form_factor": "mini"`. That single value is what makes
the presenter speak events rather than display them, across the whole system.
`capabilities.display: false` says the same thing and is the fallback if
`form_factor` is ever unset.

## Known limits

- **No echo cancellation** — worse here than elsewhere, because the speaker is
  physically closer to the mics than on a bigger build.
- **Zero 2 W WiFi is 2.4GHz only.** Fine, but it is the slowest link of any
  build here.
- **No screen means no local settings UI.** Volume, mute and wake sensitivity
  have to come from the River Song app or the physical switch. That is the
  strongest argument for fitting the switch.
