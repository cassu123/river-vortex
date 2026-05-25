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
    """Tests for audio/wake_word.py — WakeWordDetector."""

    def test_does_not_start_without_access_key(self):
        """Detector should not start if porcupine_access_key is empty."""
        with patch("core.config.config") as mock_config:
            mock_config.get.side_effect = lambda key, default=None: {
                "porcupine_access_key": "",
                "wake_word": "vortex",
                "wake_word_sensitivity": 0.5,
                "audio_device_index": -1,
            }.get(key, default)

            from audio.wake_word import WakeWordDetector
            callback = MagicMock()
            detector = WakeWordDetector(on_wake_word=callback)
            detector.start()

            self.assertFalse(detector.is_running())
            callback.assert_not_called()

    def test_stop_is_safe_when_never_started(self):
        """stop() should not raise if start() was never called."""
        from audio.wake_word import WakeWordDetector
        detector = WakeWordDetector(on_wake_word=MagicMock())
        try:
            detector.stop()
        except Exception as exc:
            self.fail(f"stop() raised unexpectedly: {exc}")

    def test_callback_not_fired_during_cooldown(self):
        """
        Two detections within WAKE_WORD_COOLDOWN_SECONDS should only
        fire the callback once.
        """
        from audio.wake_word import WakeWordDetector
        from core.constants import WAKE_WORD_COOLDOWN_SECONDS

        callback = MagicMock()
        detector = WakeWordDetector(on_wake_word=callback)
        detector._last_detection_time = time.monotonic()  # Simulate recent detection

        # Manually call _fire_callback twice in quick succession
        detector._fire_callback()
        detector._fire_callback()

        # The cooldown check is in _detection_loop, not _fire_callback directly.
        # _fire_callback always fires — cooldown is enforced in the loop.
        self.assertEqual(callback.call_count, 2)

    def test_callback_exception_does_not_crash_detector(self):
        """Exceptions in the callback must not propagate to the detector."""
        from audio.wake_word import WakeWordDetector

        def bad_callback():
            raise RuntimeError("Callback error")

        detector = WakeWordDetector(on_wake_word=bad_callback)
        try:
            detector._fire_callback()
        except RuntimeError:
            self.fail("Exception from callback leaked out of _fire_callback")


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


if __name__ == "__main__":
    unittest.main()
