import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
import time

spec = importlib.util.spec_from_file_location('controller', Path(__file__).resolve().parents[1] / 'tools' / 'airconnectctl.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class ControllerTests(unittest.TestCase):
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

if __name__ == '__main__': unittest.main()
