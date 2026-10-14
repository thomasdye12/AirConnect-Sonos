"""Dashboard regression tests; no speakers or production services are contacted."""
import binascii
import importlib.util
import importlib.machinery
import io
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

SPEC = importlib.util.spec_from_file_location('dashboard', os.path.join(os.path.dirname(__file__), '..', 'tools', 'airconnect_dashboard.py'))
if hasattr(importlib.util, 'module_from_spec'):
    d = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(d)
else:  # Python 3.4 on the bridge
    d = importlib.machinery.SourceFileLoader('dashboard', SPEC.origin).load_module()
ROOM = 'RINCON_123456789ABC01400'
OTHER = 'RINCON_123456789ABD01400'


class DashboardTests(unittest.TestCase):
    def test_logs_reset_at_restart_and_preserve_independent_sessions(self):
        text = '''[10:00:00.000] Starting airupnp version: old
[10:00:01.000] native PCM started for 192.0.2.1
[11:00:00.000] Starting airupnp version: new
[11:00:01.000] adding renderer (192.0.2.2 - Sonos - RINCON_123456789ABC01400) with mac 00
[11:00:02.000] native PCM started for 192.0.2.2
[11:00:03.000] native PCM started for 192.0.2.3
[11:00:04.000] native helper released; independent PCM continues for 192.0.2.3
[11:00:05.000] native sender 192.0.2.2 packets=12 clocks=1 late=2 pcm_frames=3012 signal_frames=3000
[11:00:06.000] native PCM timing samples=3012 wait_blocks=1 dropped_frames=0 realignments=0'''
        result = d.parse_log(text)
        self.assertEqual(result['version'], 'new')
        self.assertEqual(list(result['sessions']), ['192.0.2.3'])
        self.assertEqual(result['completed'][0]['packets'], 12)
        self.assertEqual(result['addresses'][ROOM], '192.0.2.2')
        self.assertNotIn('room', result['timing'][0])

    def test_log_truncation_clears_previous_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'log')
            with open(path, 'w') as stream: stream.write('native PCM started for 192.0.2.2\n')
            reader = d.LogReader(path)
            self.assertTrue(reader.read()['sessions'])
            with open(path, 'w') as stream: stream.write('')
            self.assertFalse(reader.read()['sessions'])

    def test_only_locks_owned_by_exact_process_count(self):
        with tempfile.TemporaryDirectory() as proc:
            fd_dir = os.path.join(proc, '123', 'fd')
            directory = os.path.join(proc, 'airconnect-native-0')
            os.makedirs(fd_dir); os.makedirs(directory)
            target = os.path.join(directory, binascii.hexlify(ROOM.encode()).decode() + '.lock')
            with open(target, 'w'): pass
            os.symlink(target, os.path.join(fd_dir, '7'))
            stat = os.stat(target)
            entry = '1: FLOCK ADVISORY WRITE {} {:02x}:{:02x}:{} 0 EOF\n'
            with open(os.path.join(proc, 'locks'), 'w') as stream:
                stream.write(entry.format(456, os.major(stat.st_dev), os.minor(stat.st_dev), stat.st_ino))
            self.assertEqual(d.held_devices(123, proc), [])
            with open(os.path.join(proc, 'locks'), 'w') as stream:
                stream.write(entry.format(123, os.major(stat.st_dev), os.minor(stat.st_dev), stat.st_ino))
            self.assertEqual(d.held_devices(123, proc), [ROOM])

    def test_config_overrides_and_group_members(self):
        with tempfile.NamedTemporaryFile(mode='w') as stream:
            stream.write('<airupnp><common><native_udp>1</native_udp></common><device><udn>uuid:' + ROOM + '</udn><native_sync_offset_ms>210</native_sync_offset_ms></device></airupnp>')
            stream.flush()
            config = d.read_config(stream.name)
        self.assertEqual(config['defaults']['native_udp'], '1')
        self.assertEqual(config['overrides'][ROOM], {'native_sync_offset_ms': '210'})
        rooms = d.normalize_zones([{'coordinator': {'uuid': ROOM, 'roomName': 'A'}, 'members': [{'uuid': ROOM, 'roomName': 'A'}, {'uuid': OTHER, 'roomName': 'B'}]}])
        self.assertEqual(rooms[1]['coordinator'], ROOM)
        self.assertEqual(rooms[1]['group_size'], 2)

    def test_reject_duplicate_rooms_and_oversized_data(self):
        zone = {'coordinator': {'uuid': ROOM, 'roomName': 'A'}}
        with self.assertRaises(ValueError): d.normalize_zones([zone, zone])
        with self.assertRaises(ValueError): d.read_json(io.BytesIO(b' ' * (d.LIMIT + 1)))

    def test_api_failure_preserves_age_and_marks_stale(self):
        collector = d.Collector('unused', 'unused')
        config = {'api': 'http://192.0.2.1/zones', 'cache': ''}
        zones = [{'coordinator': {'uuid': ROOM, 'roomName': 'A'}}]
        with mock.patch.object(d.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(zones).encode())):
            rooms, api = collector.room_snapshot(config)
        self.assertFalse(api['stale'])
        fetched = api['fetched_at']
        collector.rooms_attempt = 0
        with mock.patch.object(d.urllib.request, 'urlopen', side_effect=OSError('offline')):
            rooms, api = collector.room_snapshot(config)
        self.assertTrue(api['stale'])
        self.assertEqual(api['fetched_at'], fetched)
        self.assertEqual(rooms[0]['name'], 'A')

    def test_expired_disk_cache_rejected(self):
        with tempfile.NamedTemporaryFile(mode='w') as stream:
            json.dump({'version': 1, 'api': 'http://192.0.2.1/zones', 'fetched_at': time.time() - 90000,
                       'zones': [{'coordinator': {'uuid': ROOM, 'roomName': 'A'}}]}, stream)
            stream.flush()
            with mock.patch.object(d.urllib.request, 'urlopen', side_effect=OSError('offline')):
                rooms, api = d.Collector('unused', 'unused').room_snapshot({'api': 'http://192.0.2.1/zones', 'cache': stream.name})
        self.assertEqual(rooms, [])
        self.assertTrue(api['stale'])

    def test_collector_failure_retains_original_snapshot_time(self):
        collector = d.Collector('unused', 'unused')
        original = collector.read()['collected_at']
        with mock.patch.object(collector, 'collect', side_effect=OSError('missing config')):
            collector.refresh()
        self.assertEqual(collector.read()['collected_at'], original)
        self.assertIn('missing config', collector.read()['collector_error'])

    def test_http_is_read_only_and_fixed_routes(self):
        server = d.Server(('127.0.0.1', 0), d.Handler)
        server.allowed_hosts = {'127.0.0.1'}
        server.collector = d.Collector('unused', 'unused')
        server.collector.snapshot['large_payload'] = 'x' * (256 * 1024)
        server.assets = os.path.join(os.path.dirname(__file__), '..', 'tools', 'dashboard')
        thread = threading.Thread(target=server.serve_forever); thread.daemon = True; thread.start()
        url = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with urllib.request.urlopen(url + '/api/status') as response:
                payload = response.read()
                self.assertEqual(len(payload), int(response.headers['Content-Length']))
                data = json.loads(payload.decode('utf-8'))
                self.assertFalse(data['ready'])
                self.assertEqual(len(data['large_payload']), 256 * 1024)
                self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
            for path in ('/', '/app.js', '/style.css', '/api/diagnostics'):
                with urllib.request.urlopen(url + path) as response: self.assertEqual(response.status, 200)
            for request, code in [(urllib.request.Request(url + '/api/status', data=b'{}'), 501),
                                  (url + '/../Config.xml', 404),
                                  (urllib.request.Request(url + '/api/status', headers={'Host': 'attacker.example'}), 403)]:
                with self.assertRaises(urllib.error.HTTPError) as caught: urllib.request.urlopen(request)
                self.assertEqual(caught.exception.code, code)
                caught.exception.close()
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
