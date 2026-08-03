# Hub 7" — counter unit

**Build this one first.** You already own the Pi 4, so it is the cheapest way
to have a real unit running, and everything learned here carries to the wall
build.

Roughly a Nest Hub: sits on a worktop, shows the clock and whatever River Song
thinks matters, answers when spoken to.

## Parts

| Part | Notes | ~GBP |
|---|---|---|
| Raspberry Pi 4 (2GB+) | **You have this.** 2GB is enough — nothing here is memory hungry | — |
| Official 7" touchscreen (800×480) | DSI ribbon, no HDMI port used, backlight controllable | 60 |
| Pi 4 PSU (USB-C, 3A) | Do not use a phone charger. Undervoltage shows up as random reboots and the boot self-test will flag it | 8 |
| microSD 32GB A2 | A2 rated matters — a slow card makes the whole unit feel broken | 8 |
| ReSpeaker 2-Mic HAT **or** USB mic array | See the note below | 15–30 |
| Small powered speaker (3.5mm) | The Pi's own jack is weak; a powered speaker is the difference between hearing River from the next room and not | 15–25 |
| Case for Pi + 7" screen | SmartiPi Touch 2 or similar | 20–25 |
| Latching SPST switch | The mute switch. Any panel-mount toggle | 3 |
| 2 × 3mm LED + 330Ω resistors | Mic mute and camera active indicators | 2 |

**~£130–160** all in, minus the Pi.

### Microphone — the one decision that matters

Far-field voice is the hardest part of this build, and the cheap option really
does perform worse.

- **ReSpeaker 2-Mic HAT** — sits on the GPIO header, two mics, decent at
  conversational distance. **It occupies the GPIO pins**, so check its pinout
  against 17 / 22 / 27 before wiring the switch and LEDs; move them in
  `core/constants.py` if they clash.
- **USB mic array** — leaves GPIO free, usually better pickup, but one more
  thing sticking out of the case.

Neither does hardware echo cancellation, so a unit playing music will struggle
to hear you over itself. That is a real limitation of every Pi build here, and
the reason the MiciMike board is interesting — it has an XMOS DSP that does.

## Screen notes

800×480 is small. The frontend handles it: everything under
`@media (max-height: 600px)` shrinks rather than scrolling, so a surface card
lands beside the clock rather than pushing it off screen.

Backlight control works through `bl_power` on the official screen, which is
what makes the burn-in staircase's final stage genuinely turn the panel off
rather than just showing black.

## Wiring

Standard pins — 17 mute LED, 27 camera LED, 22 mute switch. See
[the shared wiring notes](README.md#common-wiring), especially about wiring
the switch to cut mic power as well as signalling.

No camera in this build. Add one and set `capabilities.camera` to true plus the
purposes you actually want; the camera layer refuses anything not enabled.

## Software

```bash
cp hardware/hub-7-counter.json units/vortex_profile.json
```

Then flash, boot, and pair from the River Song app. The unit shows a pairing
PIN and claims no room name until you give it one.

## Known limits

- **No echo cancellation.** Playing music makes it hard of hearing.
- **2GB Pi 4 with Chromium** is fine but not roomy. Do not also run other
  things on this box.
- **The 7" screen is 60Hz and dim in daylight.** Fine on a worktop, weak in a
  conservatory.
