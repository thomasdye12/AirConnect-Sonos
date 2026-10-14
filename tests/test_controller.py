import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
import time
import io

spec = importlib.util.spec_from_file_location('controller', Path(__file__).resolve().parents[1] / 'tools' / 'airconnectctl.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class ControllerTests(unittest.TestCase):
    def test_save_helper_uses_root_identity_and_atomic_validated_file(self):
        xml = b'<root xmlns="urn:schemas-upnp-org:device-1-0"><device><UDN>uuid:RINCON_02000000000101400</UDN><roomName>Helper</roomName><deviceList><device><UDN>uuid:WRONG_MR</UDN></device></deviceList></device></root>'
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'helper.json')
            with patch.object(c.urllib.request, 'urlopen', return_value=io.BytesIO(xml)):
                helper = c.save_helper(path, '192.0.2.20')
            self.assertEqual(helper['uuid'], 'RINCON_02000000000101400')
            self.assertEqual(c.load_helper(path), helper)
            with patch.object(c.urllib.request, 'urlopen', return_value=io.BytesIO(b'<root/>')):
                with self.assertRaises(ValueError): c.save_helper(path, '192.0.2.21')
            self.assertEqual(c.load_helper(path), helper)

    def test_saved_helper_used_and_partial_override_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'helper.json'
            path.write_text(json.dumps({'version': 1, 'helper': {'address': '192.0.2.20', 'uuid': 'RINCON_02000000000101400', 'name': 'Helper'}}))
            args = ['--helper-config', str(path), 'udp-test', '--receiver', '192.0.2.1', '--receiver-id', 'RINCON_A', '--output', 'private.json']
            with patch.object(c.os.path, 'isfile', return_value=True), patch.object(c.subprocess, 'call', return_value=1) as call:
                c.main(args)
                command = call.call_args[0][0]
                self.assertEqual(command[command.index('--coordinator') + 1], '192.0.2.20')
                self.assertEqual(command[command.index('--coordinator-id') + 1], 'RINCON_02000000000101400')
                call.reset_mock()
                with self.assertRaises(ValueError): c.main(args + ['--coordinator', '192.0.2.21'])
                call.assert_not_called()
    def test_names_and_coordinators_only(self):
        self.assertEqual(c.valid_rooms([{'coordinator': {'uuid': 'RINCON_A', 'roomName': 'Kitchen'}, 'members': []}], 'Home ', ''), [{'uuid': 'RINCON_A', 'name': 'Home Kitchen'}])
    def test_invalid_lists(self):
        zone = {'coordinator': {'uuid': 'RINCON_A', 'roomName': 'Kitchen'}}
        for zones in ([], {}, [zone, zone], [{'coordinator': {}}]):
            with self.assertRaises(ValueError): c.valid_rooms(zones)
    def test_cache_fallback_and_expiry(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(c.urllib.request, 'urlopen', side_effect=OSError('offline')):
            cache = Path(directory) / 'cache.json'
            data = {'version': 1, 'api': 'http://example.invalid/zones', 'fetched_at': time.time(), 'zones': [{'coordinator': {'uuid': 'RINCON_A', 'roomName': 'Kitchen'}}]}
            cache.write_text(json.dumps(data))
            result = c.room_list(data['api'], str(cache), '', ' (Sonos)')
            self.assertTrue(result['source'].startswith('cached'))
            self.assertEqual(result['rooms'][0]['name'], 'Kitchen (Sonos)')
            with self.assertRaises(ValueError): c.room_list('http://another.invalid/zones', str(cache), '', '')
            data['fetched_at'] -= 86401
            cache.write_text(json.dumps(data))
            with self.assertRaises(ValueError): c.room_list(data['api'], str(cache), '', '')
    def test_controller_clip_is_always_silent(self):
        with patch.object(c.subprocess, 'call', return_value=0) as call:
            self.assertEqual(c.main(['clip-test', '--receiver', '192.0.2.1', '--receiver-id', 'RINCON_TEST', '--output', 'private.json']), 0)
            command = call.call_args[0][0]
            self.assertNotIn('--audible', command)
            self.assertNotIn('--wav', command)

    def udp_args(self):
        return ['udp-test', '--receiver', '192.0.2.1', '--receiver-id', 'RINCON_A',
                '--coordinator', '192.0.2.2', '--coordinator-id', 'RINCON_B', '--output', 'private.json']

    def test_udp_controller_defaults_muted_and_propagates_probe_failure(self):
        with patch.object(c.os.path, 'isfile', return_value=True), patch.object(c.subprocess, 'call', return_value=1) as call:
            self.assertEqual(c.main(self.udp_args() + ['--mode', 'detach', '--signal', 'tone']), 1)
            command = call.call_args[0][0]
            self.assertNotIn('--audible', command)
            self.assertIn('--promote-receiver', command)
            self.assertEqual(command[command.index('--promotion-mode') + 1], 'detach')

    def test_udp_audible_requires_bounded_tone(self):
        with patch.object(c.subprocess, 'call') as call:
            for options in (['--audible'], ['--audible', '--signal', 'tone', '--seconds', '120']):
                with self.assertRaises(ValueError): c.main(self.udp_args() + options)
            call.assert_not_called()

    def test_udp_explicit_volume_35_is_forwarded(self):
        with patch.object(c.os.path, 'isfile', return_value=True), patch.object(c.subprocess, 'call', return_value=1) as call:
            c.main(self.udp_args() + ['--audible', '--signal', 'tone', '--test-volume', '35'])
            command = call.call_args[0][0]
            self.assertIn('--audible', command)
            self.assertEqual(command[command.index('--test-volume') + 1], '35')

    def test_udp_missing_library_refused_before_probe(self):
        with patch.object(c.os.path, 'isfile', return_value=False), patch.object(c.subprocess, 'call') as call:
            with self.assertRaises(RuntimeError): c.main(self.udp_args())
            call.assert_not_called()

    def test_udp_wav_explicit_audible_and_conflict(self):
        with patch.object(c.os.path, 'isfile', return_value=True), patch.object(c.subprocess, 'call', return_value=1) as call:
            c.main(self.udp_args() + ['--wav', 'private music.wav', '--audible'])
            command = call.call_args[0][0]
            self.assertEqual(command[command.index('--wav') + 1], 'private music.wav')
            self.assertIn('--audible', command)
            call.reset_mock()
            with self.assertRaises(ValueError):
                c.main(self.udp_args() + ['--wav', 'private music.wav', '--signal', 'tone'])
            call.assert_not_called()

if __name__ == '__main__': unittest.main()
