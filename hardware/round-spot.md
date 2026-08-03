# Round Spot — circular bedside unit

The cute one. A 4" circle on a bedside table or a shelf, roughly an Echo Spot:
big clock, one card when something matters, and River's orb — which is already
a circle and finally gets hardware shaped like it.

Small on purpose. This is not the unit you cook from; it is the one you glance
at from bed.

## Parts

| Part | Notes | ~GBP |
|---|---|---|
| Raspberry Pi 4 (2GB) | Pi 5 works but is wasted here. A Zero 2 W will **not** — the DSI round panels want a full-size Pi | 40 |
| [Waveshare 4" DSI Round Touch, 720×720](https://www.waveshare.com/4inch-dsi-lcd-c.htm) | 10-point capacitive, DSI ribbon, 60Hz. The one to get | 45–55 |
| PSU 5V 3A USB-C | | 8 |
| microSD 32GB A2 | | 8 |
| USB mic array (small) | Keep the GPIO header free — see the wiring note | 20–30 |
| Small speaker + I2S amp **or** powered 3.5mm | This unit sits close to you, so it needs far less volume than a kitchen build | 10–20 |
| Round enclosure | Almost certainly 3D printed. There is no off-the-shelf case for this | 0–15 |
| Latching SPST switch | Mute. A bedside unit is exactly where you want one | 3 |
| 2 × 3mm LED + 330Ω | Mic mute, camera active | 2 |

**~£135–180.**

### Bigger alternative

[Waveshare 5" HDMI Round, 1080×1080](https://www.amazon.com/waveshare-Resolution-10-Point-Compatible-Raspberry/dp/B0C14CZ2GG)
if you want more presence on a shelf. HDMI + USB rather than DSI, so it works
with more boards but uses two cables and generally gives **no backlight
control** — which downgrades the last burn-in stage to painting the screen
black. Set `screen_width` / `screen_height` to 1080 in the profile if you use
it.

## The software problem, and what was done about it

**A round screen is still a square framebuffer.** The browser has no idea its
corners are behind a bezel, so a rectangular layout loses the corner of every
card, the end of every settings row, and both ends of the boot log.

This is handled rather than ignored. `hardware.screen_shape: "round"` in the
profile reaches the frontend, which inscribes the layout in the largest square
that fits the circle — side `D/√2`, so a **14.65% inset** on every edge. That
number is geometry, not taste.

Specifically, on a round unit:

- Content is inset; **backgrounds are not**, so photos still bleed to the bezel.
- Cards centre and narrow to 68% width instead of sitting beside the clock.
- The ambient screen stacks — clock above card. Side by side does not fit in a
  circle at any size worth reading.
- The boot log drops its timing column and clips the detail text. The status
  and the label are the message; the milliseconds are diagnostic trivia.
- The mute banner becomes a chord across the top and is **not** inset, because
  the entire point of it is being impossible to miss.
- A takeover fills the circle, corners and all.

None of this loads on a rectangular unit.

## Wiring

**Check your mic choice first.** The DSI round panel uses the DSI connector,
not GPIO, so the header is free — but a GPIO mic HAT would still collide with
pins 17 / 22 / 27. A **USB mic array keeps the header clear**, which is why it
is the recommendation here rather than on the bigger builds.

Otherwise standard: see [shared wiring](README.md#common-wiring).

## Software

```bash
cp hardware/round-spot.json units/vortex_profile.json
```

The DSI panel needs a device-tree overlay. Waveshare's current instructions
ship with the display — follow those rather than anything written here, as the
overlay name has changed between OS releases.

## Known limits

- **720×720 is not much room.** The dashboard grid and the lists page are
  cramped. This build is really an ambient screen with a settings page behind
  it, and it is better for admitting that.
- **No off-the-shelf enclosure.** Expect to print one.
- **No echo cancellation**, same as every Pi build here.
- **The 5" HDMI variant usually has no backlight control**, so the final
  burn-in stage saves no power on it.
