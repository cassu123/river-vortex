# MiciMike — Nest / Home Mini drop-in board

> ⚠️ **This is not a Vortex unit, and cannot become one.** No
> `vortex_profile.json` here on purpose. The board is an **ESP32-S3**, not a
> Linux machine — the Vortex Python backend cannot run on it in any form.
>
> It is in this folder because it is the most interesting screenless hardware
> going, and because there is a plausible route to it talking to River Song.

## What it is

A replacement PCB that drops into a Google Home / Nest Mini shell, reusing the
original **speaker, three-microphone array, capacitive touch, LEDs and power**,
and replacing the brains.

- **[`home-mini-v1-drop-in-pcb`](https://github.com/iMike78/home-mini-v1-drop-in-pcb)**
  — Google Home Mini **1st gen** (micro-USB). ← the one that matches yours
- [`nest-mini-drop-in-pcb`](https://github.com/iMike78/nest-mini-drop-in-pcb)
  — Nest Mini 2nd gen (barrel jack)

**ESP32-S3** for wake word and networking, plus an **XMOS XU316 DSP** doing
acoustic echo cancellation, noise suppression and automatic gain control.

That DSP is the thing worth caring about. **Every Pi build in this folder
lacks it**, which is why a Vortex unit playing music struggles to hear you over
itself. This board solves the hardest problem in the whole product, in
hardware, in a shell you already own.

Licence: CERN-OHL-S v2.

## Why it cannot run Vortex

Vortex needs Python, mpv, ALSA and a Linux filesystem. An ESP32 has none of
those. Making this a Vortex unit would mean writing ESP32 firmware from
scratch — a different discipline and effectively a second product.

## The route that would work

There is a third repo:
**[`MiciMike-standalone-AI-firmware`](https://github.com/iMike78/MiciMike-standalone-AI-firmware)**.
It speaks the **OpenAI Realtime API over WebSocket**, pointed at **any endpoint
typed into its web UI**, and needs no Home Assistant.

So if River Song exposed an OpenAI-Realtime-compatible socket, this board would
work with **no firmware written at all** — you would type your server's address
into a settings page.

That is a River Song question, not a Vortex one, and it is a real piece of work:
a stateful bidirectional audio protocol with a specific event schema. But it
would light up this board *and* anything else that adopts the format.

**Note the default is OpenAI's own service.** Flash one of these and leave that
field alone and it genuinely sends household audio to OpenAI. Changing it is
one field, but it is a field you must not forget.

## Blockers today

1. **Both projects are experimental.** The PCB is on its second test batch with
   partial functionality; the firmware calls itself "usable, but still
   experimental".
2. **The wake word is fixed** to "Okay Nabu", "Hey Jarvis" or "Hey Mycroft".
   No "hey River" without training a microWakeWord model.
3. **River Song does not speak OpenAI Realtime**, and adding it is not small.

## Verdict

Watch it. Back the 1st-gen campaign if you want one. Do not plan around it yet
— but if a board ships and works, the question worth answering is *"should
River Song speak OpenAI Realtime?"*, because the answer unlocks a lot of
off-the-shelf hardware and not just this.

Meanwhile [`mini-screenless`](mini-screenless.md) is the screenless unit that
exists and works today.
