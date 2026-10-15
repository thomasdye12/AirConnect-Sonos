"""Exercise real C SOAP/session code against local simulated speakers only."""
import http.server
import json
import os
import sys
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import xml.etree.ElementTree as E

A, B = '127.0.0.1', os.environ.get('NATIVE_TEST_HELPER_IP', '127.0.0.2')
UA, UB = 'RINCON_02000000000101400', 'RINCON_02000000000201400'

class NativeControl(unittest.TestCase):
    def test_restore_release_and_refuse_busy_helper(self):
        if sys.platform == 'darwin' and 'NATIVE_TEST_HELPER_IP' not in os.environ:
            self.skipTest('Set NATIVE_TEST_HELPER_IP to this Mac IPv4 address; macOS lacks 127.0.0.2 alias')
        state = {ip: dict(uri='', meta='<DIDL-Lite><title>A &amp; B</title></DIDL-Lite>', volume='19', mute='0', transport='STOPPED') for ip in (A, B)}
        original = {ip: dict(v) for ip, v in state.items()}
        joined, calls, fail_promotion = [False], [], [False]
        delayed_detach, never_converge, detached_at = [False], [False], [None]
        def topology(view):
            if detached_at[0] is not None and not never_converge[0] and time.monotonic() >= detached_at[0]:
                joined[0] = False
            root = E.Element('ZoneGroups')
            groups = [(UB, [A, B])] if joined[0] else [(UA, [A]), (UB, [B])]
            if view == B and delayed_detach[0] and not joined[0]:
                # Captured Sonos behavior: helper is independently coordinated,
                # but caches the receiver in an orphaned old group indefinitely.
                groups = [('', [A]), (UB, [B])]
            for coord, members in groups:
                group = E.SubElement(root, 'ZoneGroup', Coordinator=coord, ID=coord + ':1')
                for ip in members:
                    E.SubElement(group, 'ZoneGroupMember', UUID=UA if ip == A else UB, Location='http://' + ip + ':1400/xml/device_description.xml')
            return E.tostring(root, encoding='unicode')
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                ip = self.connection.getsockname()[0]
                assert self.client_address[0] in (A, B)
                request = E.fromstring(self.rfile.read(int(self.headers['Content-Length'])))
                body = next(e for e in request.iter() if e.tag.endswith('Body'))
                command = list(body)[0]; name = command.tag.split('}')[-1]
                args = {e.tag.split('}')[-1]: e.text or '' for e in command}
                calls.append((ip, name))
                if name == 'BecomeGroupCoordinator' and fail_promotion[0]:
                    self.send_response(500); self.send_header('Content-Length', '0'); self.end_headers(); return
                result = {}
                if name == 'GetZoneGroupState': result['ZoneGroupState'] = topology(ip)
                elif name == 'GetTransportInfo': result['CurrentTransportState'] = state[ip]['transport']
                elif name == 'GetMediaInfo': result.update(CurrentURI=state[ip]['uri'], CurrentURIMetaData=state[ip]['meta'])
                elif name == 'GetMute': result['CurrentMute'] = state[ip]['mute']
                elif name == 'GetVolume': result['CurrentVolume'] = state[ip]['volume']
                elif name == 'SetMute': state[ip]['mute'] = args['DesiredMute']
                elif name == 'SetVolume': state[ip]['volume'] = args['DesiredVolume']
                elif name == 'SetAVTransportURI':
                    state[ip]['uri'], state[ip]['meta'] = args['CurrentURI'], args['CurrentURIMetaData']
                    if ip == A and args['CurrentURI'].startswith('x-rincon:'): joined[0] = True
                elif name in ('BecomeGroupCoordinator', 'BecomeCoordinatorOfStandaloneGroup'):
                    if delayed_detach[0] and name == 'BecomeGroupCoordinator':
                        pass  # Acknowledged, but topology still shows old membership.
                    elif delayed_detach[0] and ip == B and joined[0]:
                        detached_at[0] = time.monotonic() + .6
                    else:
                        joined[0] = False
                    if name == 'BecomeGroupCoordinator':
                        assert self.headers.get('x-sonos-clone-gc') == '1'
                elif name == 'Stop': state[ip]['transport'] = 'STOPPED'
                elif name not in ('ChangeTransportSettings', 'RemoveMember'): raise AssertionError(name)
                response = E.Element('Response')
                for key, value in result.items(): E.SubElement(response, key).text = value
                raw = E.tostring(response)
                self.send_response(200); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
        servers, threads = [], []
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); rx.bind((A, 7020)); rx.settimeout(.1)
        stop = threading.Event()
        def drain():
            while not stop.is_set():
                try: rx.recvfrom(2048)
                except socket.timeout: pass
        audio = threading.Thread(target=drain); audio.start()
        try:
            for ip in (A, B):
                server = http.server.HTTPServer((ip, 1400), Handler); servers.append(server)
                thread = threading.Thread(target=server.serve_forever); thread.start(); threads.append(thread)
            with tempfile.TemporaryDirectory() as directory:
                helper = Path(directory) / 'helper.json'
                helper.write_text(json.dumps({'version': 1, 'helper': {'address': B, 'uuid': UB, 'name': 'Test helper'}}))
                driver = Path(__file__).parent / 'bin/native_output_driver'
                command = [str(driver), str(helper), A, 'http://' + A + ':1400/xml/device_description.xml', 'uuid:' + UA, '7', '25']
                run = subprocess.run(command, capture_output=True, text=True, timeout=25)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertIn('native helper released', run.stderr)
                self.assertEqual(run.stderr.count(': verified'), 2)
                self.assertEqual(state, original)
                # The final receiver restore must not query or mutate the helper.
                close_start = max(i for i, (ip, action) in enumerate(calls) if ip == A and action == 'BecomeCoordinatorOfStandaloneGroup')
                self.assertFalse(any(ip == B for ip, action in calls[close_start:]))
                # Regression: detach ACK precedes topology convergence. Continue
                # sending PCM while waiting, then release/restore the helper.
                calls.clear(); delayed_detach[0] = True
                longer = list(command); longer[-2] = '11'
                run = subprocess.run(longer, capture_output=True, text=True, timeout=25)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertIn((B, 'RemoveMember'), calls)
                self.assertIn('native helper released', run.stderr)
                self.assertEqual(run.stderr.count(': verified'), 2)
                self.assertEqual(state, original)
                # A topology which never converges must still fail and restore.
                calls.clear(); detached_at[0] = None; never_converge[0] = True
                run = subprocess.run(longer, capture_output=True, text=True, timeout=25)
                self.assertEqual(run.returncode, 6, run.stderr)
                self.assertIn('timed out waiting for receiver/helper separation', run.stderr)
                self.assertEqual(run.stderr.count(': verified'), 2)
                self.assertEqual(state, original)
                delayed_detach[0] = never_converge[0] = False; detached_at[0] = None
                calls.clear(); fail_promotion[0] = True
                run = subprocess.run(command, capture_output=True, text=True, timeout=20)
                self.assertEqual(run.returncode, 6, run.stderr)
                self.assertIn('native control failed', run.stderr)
                self.assertEqual(run.stderr.count(': verified'), 2)
                self.assertEqual(state, original)
                calls.clear(); state[B]['transport'] = 'PLAYING'
                run = subprocess.run(command, capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, 5, run.stderr)
                self.assertTrue(all(action.startswith('Get') for ip, action in calls))
                self.assertEqual(state[A], original[A])
        finally:
            stop.set(); audio.join(); rx.close()
            for server in servers: server.shutdown(); server.server_close()
            for thread in threads: thread.join()

if __name__ == '__main__': unittest.main()
