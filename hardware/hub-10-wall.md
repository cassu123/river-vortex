# Hub 10" — wall panel

The big one. Mounted flush on a wall, landscape or portrait, showing the clock
and photos most of the time and whatever River Song raises the rest of it.

Portrait is worth considering: you mentioned wanting the avatar to be able to
"affect stuff" — swipe, point, cover the screen. A portrait panel gives a
figure room to stand in, and the surface renderer already reflows for it.

## Parts

| Part | Notes | ~GBP |
|---|---|---|
| Raspberry Pi 4 (4GB) or Pi 5 | Pi 5 if you have it spare. **If you only have one Pi 5, keep it for River Vector** — it is the only board that takes the AI HAT+ | 45–70 |
| 10.1" IPS touchscreen (1280×800) | HDMI + USB touch. Get one with a **controller board that exposes backlight PWM** — see below | 65–90 |
| PSU 5V 3A (Pi 4) / 5A (Pi 5) | Pi 5 genuinely needs 5A under load | 8–12 |
| microSD 32GB A2 or NVMe (Pi 5) | NVMe on a Pi 5 makes boot noticeably quicker | 8–25 |
| ReSpeaker 4-Mic Array HAT | Four mics, circular. Best far-field pickup of the Pi options | 30 |
| Small amp + 2 × 3W speakers | Wall panels are further from your face than a counter unit; on-board audio is not enough | 20–30 |
| Flush mount frame / recessed box | The part that decides whether this looks built-in or bodged | 25–60 |
| Latching SPST switch | Mute. Mount it where you can reach without a ladder | 3 |
| 2 × 3mm LED + 330Ω resistors | Mic mute and camera active | 2 |
| **Optional** Pi Camera Module 3 | Only if you want the camera features. See below | 25 |

**~£230–330** depending on screen and mount.

### The backlight problem — read before buying the screen

The burn-in staircase ends by cutting the backlight. On the **official DSI**
screen that works through `bl_power`. On a **generic HDMI panel it usually does
not**, and the best the software can do is paint the screen black — which
saves no power and does not stop the panel wearing.

Before ordering, check the controller board exposes brightness or backlight
control over something addressable. If it does not, the unit still works, the
final burn-in stage is just cosmetic. The boot self-test reports this honestly
as `DISPLAY … no backlight control` rather than pretending.

## Portrait mounting

Set `display.screen_rotation` to `90` in the profile and rotate the framebuffer
in `/boot/firmware/cmdline.txt` (or `config.txt`, depending on OS version).

The frontend does not need telling: the surface layout wraps on its own, so
cards stack under the clock in portrait and sit beside it in landscape.

## Camera

Left **off** in the shipped profile. If you fit one, set
`capabilities.camera` to `true` and enable only the purposes you want:

```json
"camera_purposes": {
  "video_calls": true,
  "motion_snapshots": false,
  "presence": false,
  "face_recognition": false
}
```

Each is consented separately and the capture layer refuses anything not
enabled. Agreeing to video call the kitchen is not agreeing to have your face
matched against a roster.

Wire the camera active LED (pin 27) if you fit a camera. It is driven by the
capture session itself, so frames are impossible without the light on — and it
is the only thing standing between a wall-mounted lens and a lens nobody can
tell is live.

## Wiring

See [shared wiring](README.md#common-wiring). The 4-Mic HAT uses a lot of
the GPIO header — check its pinout against 17 / 22 / 27 and move them in
`core/constants.py` if needed.

## Software

```bash
cp hardware/hub-10-wall.json units/vortex_profile.json
```

For portrait, change `screen_rotation` to `90` before flashing.

## Known limits

- **Backlight control is a lottery** on generic panels — above.
- **No echo cancellation**, same as every Pi build.
- **Heat.** In a recessed box with no airflow a Pi 5 will throttle. The boot
  self-test has a thermal check; watch it for the first few days.
