# Satellite — jailbroken Echo Show

> ⚠️ **This is not a Vortex unit.** There is no `vortex_profile.json` in this
> folder on purpose. An Echo Show runs Android; the Vortex backend is Python
> and needs a real microphone, mpv, ALSA and GPIO. None of that runs here.
>
> What this *can* be is a **cheap extra screen** showing the Vortex frontend,
> with the actual unit running on a Pi somewhere else.

## What the hack is

Unlock the bootloader, wipe Fire OS, flash **LineageOS 18.1 (Android 11)**. You
end up with an ordinary Android tablet that happens to have a good speaker.

**Only three models work** — Echo Show 5 gen 1, Echo Show 5 gen 2, Echo Show 8
gen 1. The exploit needs the micro-USB port, so Show 8 gen 2+, Show 15 and
Show 21 are permanently out.

Sources: [Derek Seaman's guide](https://www.derekseaman.com/2025/11/home-assistant-hacking-your-echo-show-5-and-8.html)
· [XDA thread](https://xdaforums.com/t/rom-unofficial-11-cronos-lineageos-18-1-for-the-amazon-echo-show-5-2021.4772598/)
· [Hackaday](https://hackaday.com/2026/01/02/jailbreaking-the-amazon-echo-show/)

## Cost

**~£30–50** for a used Show 5, against £130–160 for the 7" Pi build. That gap
is the entire argument for doing this.

## What breaks

- **The camera does not work.** Kills every camera feature on that unit.
- **Microphone quality is poor** on these builds — reported quieter than it
  should be. That undermines wake word, which is the point of a Vortex unit.
- **Bluetooth and speaker quality** have known issues.
- The builds are **experimental**, and bricking is a real risk.

The two things that break worst are the two that matter most, which is why this
is filed as a satellite screen rather than a unit.

## What would be needed to actually use it

Not built, and not free:

1. **The Vortex API is loopback-only, deliberately.** It has no authentication
   and exposes mic mute state, camera snapshots and privacy controls. Pointing
   an Echo Show at a Pi means exposing that to your LAN, so **device API
   authentication has to exist first.**
2. A kiosk browser on the Show (Fully Kiosk or similar) pointed at that Pi.
3. A decision about what a screen with no local backend should do when the Pi
   it depends on is unreachable.

Item 1 is the blocker. It is real work, not a config change.

## Verdict

Worth **one** used unit as an experiment if you want a cheap extra panel in a
room where voice does not matter — a hallway display, say. Not worth planning
around, and not a replacement for a Pi build.

If the mic really is as weak as reported, you find out for £40 instead of
committing a plan to it.
