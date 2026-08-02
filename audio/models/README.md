# Wake word models

Drop `.onnx` (preferred) or `.tflite` openWakeWord models in this directory.
They are baked into the unit image and loaded from disk at runtime.

## Why they are not downloaded

openWakeWord can fetch its pretrained models on first use. That is deliberately
disabled here. A unit whose entire promise is "nothing leaves the house" must
not reach out to a model host the first time someone speaks to it — and a unit
with no internet on first boot would simply never hear its wake word.

Provisioning is a build step, not a runtime one.

## Naming

The filename is derived from the wake word phrase in the user's River Song
profile: lowercased, non-alphanumerics collapsed to underscores.

| Phrase in the profile | Model file expected |
|---|---|
| `Hey River` | `hey_river.onnx` |
| `sup river` | `sup_river.onnx` |
| `hey jarvis` | `hey_jarvis.onnx` |

If the model is missing the unit still boots and the touchscreen still works —
it just cannot be woken by voice, and the boot self-test says so on screen.

## Provisioning — do this in the image build

**Two things are needed, and it is easy to install only the first.**

1. **The wake word model** — the file that recognises your phrase, which goes
   in this directory.
2. **The shared feature models** — `melspectrogram`, `embedding_model` and
   `silero_vad`. Every wake word model depends on these, and openWakeWord
   loads them from inside its own package, not from here. Without them nothing
   works no matter what is in this folder.

Run this during the image build, on a machine with internet:

```bash
pip install openwakeword onnxruntime
python -c "import openwakeword.utils; openwakeword.utils.download_models()"
```

That fetches the shared models into the installed package **and** the
pretrained wake words (`alexa`, `hey_mycroft`, `hey_jarvis`, `hey_rhasspy`).

Then copy the wake word you want into this directory, renamed to match the
phrase in the River Song profile:

```bash
python - <<'EOF'
import openwakeword, os, shutil
src = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
shutil.copy(os.path.join(src, "hey_jarvis_v0.1.onnx"), "audio/models/hey_jarvis.onnx")
EOF
```

Note the version suffix on the source filename (`_v0.1`) — it is stripped in
the copy, because the destination name has to match the phrase, not the
release.

## "Hey River"

There is no pretrained model for it — River is not one of openWakeWord's stock
phrases. Training a custom one is a separate exercise using
[openWakeWord's training notebook](https://github.com/dscripka/openWakeWord),
which generates synthetic speech for the phrase and trains against it. The
output is a `.onnx` file that goes here like any other.

Until then, pick one of the stock phrases in the River Song profile so the two
halves agree. A unit listening for a phrase whose model it does not have is a
unit that never wakes up.
