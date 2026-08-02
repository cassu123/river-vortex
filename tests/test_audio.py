"""
================================================================================
Project:     River Vortex — Smart Home Hub for the River Song AI Ecosystem
File:        tests/test_audio.py
Purpose:     Unit tests for the audio subsystem — wake word detector,
             microphone, speaker, and audio manager. Uses mocks for all
             hardware dependencies (PyAudio, pvporcupine) so tests run
             on any machine without physical audio hardware.
Author:      [Author Placeholder]
Version:     1.0.0
Date:        2026-05-25
License:     Internal Use Only — River Song AI / riversongai.com
================================================================================
"""

import asyncio
import threading
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def run_async(coro):
    """Run an async coroutine synchronously in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ─────────────────────────────────────────────────────────────────────────────
# WakeWordDetector tests
# ─────────────────────────────────────────────────────────────────────────────

class TestWakeWordDetector(unittest.TestCase):
    """
    Tests for audio/wake_word.py — WakeWordDetector, on openWakeWord.

    The Porcupine engine was replaced because it required a Picovoice access
    key: a commercial licence dependency in the one part of the system whose
    whole claim is that nothing leaves the house. These assert the properties
    that made the swap worth doing.
    """

    def _detector(self, callback=None, **settings):
        from audio.wake_word import WakeWordDetector
        base = {"wake_word": "hey jarvis", "wake_word_threshold": 0.5,
                "wake_word_model_dir": "audio/models", "audio_device_index": -1}
        base.update(settings)
        patcher = patch("audio.wake_word.config")
        cfg = patcher.start()
        self.addCleanup(patcher.stop)
        cfg.get.side_effect = lambda key, default=None: base.get(key, default)
        return WakeWordDetector(on_wake_word=callback or MagicMock())

    def test_the_module_no_longer_depends_on_porcupine(self):
        """
        The point of the swap: no licence key, no account, no vendor SDK.

        Checks the imports rather than the file text, because the docstring
        legitimately explains why Porcupine was replaced and that prose should
        not be what keeps this test passing.
        """
        import ast
        import audio.wake_word as module

        tree = ast.parse(open(module.__file__).read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        self.assertNotIn("pvporcupine", imported)
        self.assertIn("openwakeword", imported)

    def test_no_access_key_is_read_from_config(self):
        """A licence key read at startup is the dependency being removed."""
        import ast
        import audio.wake_word as module

        tree = ast.parse(open(module.__file__).read())
        keys = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertFalse([k for k in keys if "access_key" in k],
                         "wake word detection still reads a licence key")

    def test_porcupine_is_gone_from_requirements(self):
        """Leaving it installed leaves the dependency, however unused."""
        requirements = open("requirements.txt").read().lower()
        self.assertNotIn("pvporcupine==", requirements)
        self.assertIn("openwakeword", requirements)

    def test_a_missing_model_disables_voice_without_crashing(self):
        """
        A unit that cannot hear its name is degraded, not broken — the
        touchscreen still works and River Song can still push to it.
        """
        callback = MagicMock()
        detector = self._detector(callback, wake_word="not_a_real_model")
        detector.start()
        self.assertFalse(detector.is_running())
        callback.assert_not_called()

    def test_stop_is_safe_when_never_started(self):
        detector = self._detector()
        try:
            detector.stop()
        except Exception as exc:
            self.fail(f"stop() raised unexpectedly: {exc}")

    def test_the_cooldown_suppresses_a_second_detection(self):
        """Otherwise one utterance fires the command flow several times."""
        callback = MagicMock()
        detector = self._detector(callback)
        detector._maybe_fire()
        detector._maybe_fire()
        self.assertEqual(callback.call_count, 1)

    def test_a_detection_after_the_cooldown_fires_again(self):
        from core.constants import WAKE_WORD_COOLDOWN_SECONDS
        callback = MagicMock()
        detector = self._detector(callback)
        detector._maybe_fire()
        detector._last_detection_time -= (WAKE_WORD_COOLDOWN_SECONDS + 1)
        detector._maybe_fire()
        self.assertEqual(callback.call_count, 2)

    def test_a_callback_exception_does_not_crash_the_detector(self):
        def bad_callback():
            raise RuntimeError("Callback error")
        detector = self._detector(bad_callback)
        try:
            detector._maybe_fire()
        except RuntimeError:
            self.fail("Exception from callback leaked out of the detector")

    def test_scores_above_the_threshold_count_as_a_detection(self):
        detector = self._detector(wake_word_threshold=0.5)
        self.assertTrue(detector._is_detection({"hey_jarvis": 0.9}))
        self.assertTrue(detector._is_detection({"hey_jarvis": 0.5}))
        self.assertFalse(detector._is_detection({"hey_jarvis": 0.49}))

    def test_the_score_is_read_by_value_not_by_model_name(self):
        """
        openWakeWord keys the result on whatever it derived from the file
        path. Looking it up by the expected name would silently never fire.
        """
        detector = self._detector(wake_word_threshold=0.5)
        self.assertTrue(detector._is_detection({"/some/odd/path.onnx": 0.8}))

    def test_a_malformed_score_is_not_a_detection(self):
        detector = self._detector()
        for junk in (None, "loud", 42, {"x": "loud"}):
            self.assertFalse(detector._is_detection(junk))


class TestWakeWordNaming(unittest.TestCase):
    """The phrase lives in River Song; the filename lives on the unit."""

    def test_a_human_phrase_becomes_a_model_filename(self):
        from audio.wake_word import model_name_for
        self.assertEqual(model_name_for("Hey River"), "hey_river")
        self.assertEqual(model_name_for("sup river"), "sup_river")
        self.assertEqual(model_name_for("Hey, River!"), "hey_river")

    def test_an_empty_phrase_falls_back_to_the_default(self):
        from audio.wake_word import model_name_for
        from core.constants import DEFAULT_WAKE_WORD
        self.assertEqual(model_name_for(""), DEFAULT_WAKE_WORD)
        self.assertEqual(model_name_for(None), DEFAULT_WAKE_WORD)

    def test_available_models_reports_nothing_for_a_missing_directory(self):
        from audio.wake_word import available_models
        self.assertEqual(available_models("/nonexistent/models"), [])

    def test_available_models_strips_extensions_and_deduplicates(self):
        import tempfile, os
        from audio.wake_word import available_models
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("hey_river.onnx", "hey_river.tflite",
                         "alexa.onnx", "notes.txt"):
                open(os.path.join(tmp, name), "w").close()
            self.assertEqual(available_models(tmp), ["alexa", "hey_river"])


# ─────────────────────────────────────────────────────────────────────────────
# Microphone tests
# ─────────────────────────────────────────────────────────────────────────────

class TestMicrophone(unittest.TestCase):
    """Tests for audio/microphone.py — Microphone."""

    def test_read_frame_raises_when_not_open(self):
        """read_frame() must raise MicrophoneError if stream is not open."""
        from audio.microphone import Microphone, MicrophoneError
        mic = Microphone()
        with self.assertRaises(MicrophoneError):
            mic.read_frame()

    def test_mute_returns_silence(self):
        """read_frame() should return silence bytes when muted."""
        from audio.microphone import Microphone
        from core.constants import AUDIO_CHUNK_SIZE

        mic = Microphone()
        # Inject a fake open stream
        mic._stream = MagicMock()
        mic._stream.read.return_value = b"\x01" * (AUDIO_CHUNK_SIZE * 2)

        mic.mute()
        result = mic.read_frame()

        # Should be all zeros (silence), not the fake stream data
        self.assertEqual(result, b"\x00" * (AUDIO_CHUNK_SIZE * 2))
        mic._stream.read.assert_not_called()

    def test_unmute_reads_from_stream(self):
        """read_frame() should read from the stream when not muted."""
        from audio.microphone import Microphone
        from core.constants import AUDIO_CHUNK_SIZE

        fake_audio = b"\x10" * (AUDIO_CHUNK_SIZE * 2)
        mic = Microphone()
        mic._stream = MagicMock()
        mic._stream.read.return_value = fake_audio

        mic.unmute()
        result = mic.read_frame()

        self.assertEqual(result, fake_audio)

    def test_is_muted_property(self):
        """is_muted should reflect mute/unmute calls."""
        from audio.microphone import Microphone
        mic = Microphone()
        self.assertFalse(mic.is_muted)
        mic.mute()
        self.assertTrue(mic.is_muted)
        mic.unmute()
        self.assertFalse(mic.is_muted)

    def test_is_open_property(self):
        """is_open should be False before open() and True after injecting stream."""
        from audio.microphone import Microphone
        mic = Microphone()
        self.assertFalse(mic.is_open)
        mic._stream = MagicMock()
        self.assertTrue(mic.is_open)

    @patch("pyaudio.PyAudio")
    def test_list_devices_returns_list(self, mock_pyaudio_cls):
        """list_devices() should return a list (may be empty on mock)."""
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 0
        mock_pyaudio_cls.return_value = mock_pa

        from audio.microphone import Microphone
        devices = Microphone.list_devices()
        self.assertIsInstance(devices, list)


# ─────────────────────────────────────────────────────────────────────────────
# Speaker tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSpeaker(unittest.TestCase):
    """Tests for audio/speaker.py — Speaker."""

    def test_volume_clamped_to_range(self):
        """set_volume() should clamp values to [MIN_VOLUME, MAX_VOLUME]."""
        from audio.speaker import Speaker
        from core.constants import MAX_VOLUME, MIN_VOLUME

        speaker = Speaker()
        speaker.set_volume(-10)
        self.assertEqual(speaker.get_volume(), MIN_VOLUME)

        speaker.set_volume(999)
        self.assertEqual(speaker.get_volume(), MAX_VOLUME)

        speaker.set_volume(50)
        self.assertEqual(speaker.get_volume(), 50)

    def test_stop_safe_when_not_started(self):
        """stop() should not raise if start() was never called."""
        from audio.speaker import Speaker
        speaker = Speaker()
        try:
            speaker.stop()
        except Exception as exc:
            self.fail(f"stop() raised unexpectedly: {exc}")

    def test_play_queues_item(self):
        """play() should add an item to the playback queue."""
        from audio.speaker import Speaker
        speaker = Speaker()
        speaker.play(b"\x00\x01\x02")
        self.assertEqual(speaker._playback_queue.qsize(), 1)

    def test_play_interrupt_drains_queue(self):
        """play(interrupt=True) should drain existing queue items."""
        from audio.speaker import Speaker
        speaker = Speaker()
        # Fill queue with dummy items
        for _ in range(5):
            speaker._playback_queue.put(b"dummy")

        speaker.play(b"\xff\xfe", interrupt=True)

        # Queue should have exactly 1 item (the new one)
        self.assertEqual(speaker._playback_queue.qsize(), 1)


# ─────────────────────────────────────────────────────────────────────────────
# AudioManager tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAudioManager(unittest.TestCase):
    """Tests for audio/audio_manager.py — AudioManager."""

    @patch("audio.audio_manager.WakeWordDetector")
    @patch("audio.audio_manager.Speaker")
    @patch("audio.audio_manager.Microphone")
    def test_start_initializes_all_components(
        self, mock_mic_cls, mock_speaker_cls, mock_wwd_cls
    ):
        """start() should initialize microphone, speaker, and wake word detector."""
        mock_mic = MagicMock()
        mock_speaker = MagicMock()
        mock_wwd = MagicMock()
        mock_mic_cls.return_value = mock_mic
        mock_speaker_cls.return_value = mock_speaker
        mock_wwd_cls.return_value = mock_wwd

        from audio.audio_manager import AudioManager
        manager = AudioManager()
        run_async(manager.start())

        mock_mic.open.assert_called_once()
        mock_speaker.start.assert_called_once()
        mock_wwd.start.assert_called_once()

    @patch("audio.audio_manager.WakeWordDetector")
    @patch("audio.audio_manager.Speaker")
    @patch("audio.audio_manager.Microphone")
    def test_stop_cleans_up_all_components(
        self, mock_mic_cls, mock_speaker_cls, mock_wwd_cls
    ):
        """stop() should stop all components."""
        mock_mic = MagicMock()
        mock_speaker = MagicMock()
        mock_wwd = MagicMock()
        mock_mic_cls.return_value = mock_mic
        mock_speaker_cls.return_value = mock_speaker
        mock_wwd_cls.return_value = mock_wwd

        from audio.audio_manager import AudioManager
        manager = AudioManager()
        run_async(manager.start())
        run_async(manager.stop())

        mock_wwd.stop.assert_called_once()
        mock_mic.close.assert_called_once()
        mock_speaker.stop.assert_called_once()

    @patch("audio.audio_manager.WakeWordDetector")
    @patch("audio.audio_manager.Speaker")
    @patch("audio.audio_manager.Microphone")
    def test_play_chime_delegates_to_speaker(
        self, mock_mic_cls, mock_speaker_cls, mock_wwd_cls
    ):
        """play_chime() should delegate to the speaker with the given chime type."""
        mock_speaker = MagicMock()
        mock_speaker_cls.return_value = mock_speaker

        from audio.audio_manager import AudioManager
        manager = AudioManager()
        run_async(manager.start())
        manager.play_chime("done")

        mock_speaker.play_chime.assert_called_once_with("done")


if __name__ == "__main__":
    unittest.main()
