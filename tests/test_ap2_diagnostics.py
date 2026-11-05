"""Operator reports must not turn silent transport into a playback success."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('diagnose', Path(__file__).resolve().parents[1] / 'integrations/airplay2/diagnose.py')
diagnose = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnose)


class DiagnosticsTest(unittest.TestCase):
    def report(self, text):
        return diagnose.analyse(text.splitlines())

    def test_dither_frames_are_not_audible_success(self):
        r = self.report('ap2 PCM received=3304982 late=0 silence=20 input_peak=1 output_peak=1')
        self.assertEqual(r['status'], 'input_near_silent')
        self.assertFalse(r['audible_playback_verified'])

    def test_signal_lost_in_timeline(self):
        r = self.report('ap2 PCM received=44100 late=44000 silence=44100 input_peak=9000 output_peak=0')
        self.assertEqual(r['status'], 'output_near_silent')

    def test_new_failed_session_does_not_inherit_old_signal(self):
        r = self.report('ap2 worker start: source=old muted=0\nap2 PCM received=44100 input_peak=9000 output_peak=9000\nap2 worker closed rc=0 received=44100\nap2 worker start: source=new muted=1\nap2 worker: could not open receiver: busy')
        self.assertEqual(r['status'], 'worker_failed')
        self.assertEqual(r['build'], 'new')
        self.assertIsNone(r['peaks']['output_peak'])

    def test_short_session_final_peaks_are_available(self):
        r = self.report('ap2 worker start: source=new muted=0\nap2 worker closed rc=0 received=441 input_peak=9000 output_peak=8800')
        self.assertEqual(r['status'], 'pcm_signal_present')
        self.assertTrue(r['session_closed'])
        self.assertFalse(r['audible_playback_verified'])

    def test_legacy_counters_do_not_invent_signal(self):
        r = self.report('ap2 worker closed rc=0 received=44100 late=0 silence=0')
        self.assertEqual(r['status'], 'levels_unavailable')

    def test_restoration_failure_overrides_clean_exit(self):
        r = self.report('native restore 192.0.2.1: FAILED\nap2 worker closed rc=0 received=44100 input_peak=9000 output_peak=9000')
        self.assertEqual(r['status'], 'restoration_failed')

    def test_legacy_restart_resets_evidence(self):
        r = self.report('ap2 PCM received=88200 input_peak=9000 output_peak=9000\nap2 PCM received=44100 input_peak=1 output_peak=1')
        self.assertEqual(r['status'], 'input_near_silent')


if __name__ == '__main__':
    unittest.main()
