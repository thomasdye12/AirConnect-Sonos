import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from device_lease import DeviceLease


class LeaseTests(unittest.TestCase):
    def test_process_exclusion_release_and_independent_receivers(self):
        with tempfile.TemporaryDirectory() as directory:
            code = ('from device_lease import DeviceLease\n'
                    'import sys\n'
                    'try:\n'
                    ' with DeviceLease(sys.argv[1], 0, sys.argv[2]): pass\n'
                    'except TimeoutError: sys.exit(7)\n')
            def attempt(identity):
                return subprocess.run([sys.executable, '-c', code, identity, directory],
                                      cwd=str(Path(__file__).parent), timeout=5).returncode
            with DeviceLease('receiver', 0, directory):
                with DeviceLease('helper', 0, directory) as helper:
                    self.assertEqual(attempt('helper'), 7)
                    self.assertEqual(attempt('different receiver'), 0)
                    helper.release()
                    self.assertEqual(attempt('helper'), 0)
                    self.assertEqual(attempt('receiver'), 7)
                self.assertEqual(attempt('receiver'), 7)
            self.assertEqual(attempt('receiver'), 0)

    def test_exception_releases_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                with DeviceLease('device', 0, directory):
                    raise RuntimeError('setup failed')
            with DeviceLease('device', 0, directory): pass
