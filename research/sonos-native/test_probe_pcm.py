import math
import struct
import unittest
from pathlib import Path
import tempfile
import wave

from probe_pcm import FRAMES, RATE, pcm_packet, load_wav


class PcmTests(unittest.TestCase):
    def test_default_is_zero_pcm(self):
        self.assertEqual(pcm_packet(0, 10), bytes(1004))

    def test_tone_format_amplitude_and_packet_boundary(self):
        count = 1000
        for index in (99, 100):
            samples = list(struct.iter_unpack('<hh', pcm_packet(index, count, 'tone')))
            self.assertEqual(len(samples), FRAMES)
            for j, (left, right) in enumerate(samples):
                frame = index * FRAMES + j
                expected = round(6000 * math.sin(2 * math.pi * 440 * frame / RATE))
                self.assertEqual((left, right), (expected, expected))
                self.assertLessEqual(abs(left), 6000)

    def test_fades_start_and_end_at_zero(self):
        self.assertEqual(pcm_packet(0, 100, 'tone')[:4], bytes(4))
        self.assertEqual(pcm_packet(99, 100, 'tone')[-4:], bytes(4))
        self.assertNotEqual(pcm_packet(50, 100, 'tone'), bytes(1004))

    def test_invalid_signal_or_range_rejected(self):
        for args in ((0, 0), (-1, 2), (2, 2), (0, 2, 'unknown')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                pcm_packet(*args)

    def test_wav_bounded_read_preserves_stereo_and_fades_edges(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.wav'
            with wave.open(str(path), 'wb') as w:
                w.setparams((2, 2, RATE, 0, 'NONE', 'not compressed'))
                w.writeframes(struct.pack('<hh', 12000, -9000) * (RATE * 2))
            pcm = load_wav(path, 1)
            self.assertEqual(len(pcm), int(RATE / FRAMES) * FRAMES * 4)
            self.assertEqual(pcm[:4], bytes(4))
            self.assertEqual(pcm[-4:], bytes(4))
            self.assertEqual(struct.unpack_from('<hh', pcm, 12000 * 4), (12000, -9000))

    def test_short_or_incompatible_wav_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample.wav'
            for channels, rate in ((1, RATE), (2, 48000), (2, RATE)):
                with wave.open(str(path), 'wb') as w:
                    w.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))
                    w.writeframes(bytes(100 * channels * 2))
                with self.subTest(channels=channels, rate=rate), self.assertRaises(ValueError):
                    load_wav(path, 1)
