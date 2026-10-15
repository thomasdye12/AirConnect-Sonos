"""No real speakers: WebSocket protocol, authentication, admission and cleanup."""
import base64
import importlib.machinery
import io
import json
import os
import socket
import struct
import tempfile
import threading
import time
import unittest
from unittest import mock

path = os.path.join(os.path.dirname(__file__), '..', 'tools', 'airconnect_intercom.py')
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location('intercom', path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
except AttributeError:
    m = importlib.machinery.SourceFileLoader('intercom', path).load_module()

ROOM = {'name': 'Test room', 'uuid': 'RINCON_123456789ABC01400', 'address': '127.0.0.1'}
START = {'type': 'start', 'room': 'Test room', 'format': 's16le', 'rate': 44100, 'channels': 2, 'muted': True}


def masked(opcode, data):
    mask = b'abcd'
    head = struct.pack('BB', 128 | opcode, 128 | len(data)) if len(data) < 126 else struct.pack('!BBH', 128 | opcode, 254, len(data))
    return head + mask + bytes(bytearray(c ^ mask[i % 4] for i, c in enumerate(bytearray(data))))


def incoming(sock):
    first, length = struct.unpack('BB', m.exact(sock, 2))
    if length == 126: length = struct.unpack('!H', m.exact(sock, 2))[0]
    data = m.exact(sock, length)
    return first & 15, json.loads(data.decode()) if first & 15 == 1 else data


class IntercomTests(unittest.TestCase):
    def test_short_pipe_stall_recovers_but_sustained_congestion_is_bounded(self):
        import fcntl
        read_fd, write_fd = os.pipe()
        fcntl.fcntl(write_fd, fcntl.F_SETFL, os.O_NONBLOCK)
        pipe = os.fdopen(write_fd, 'wb', buffering=0)
        session = m.Session(m.Manager({}), ROOM, 25, True)
        session.process = mock.Mock(stdin=pipe)
        session.process.poll.return_value = None
        def fill():
            total = 0
            while True:
                try: total += os.write(write_fd, b'\0' * 4096)
                except BlockingIOError: return total
        received = bytearray()
        try:
            count = fill(); payload = b'\1\0\1\0' * 2048
            def drain():
                time.sleep(.2)
                while len(received) < count + len(payload): received.extend(os.read(read_fd, 4096))
            thread = threading.Thread(target=drain); thread.start()
            session.write(payload); thread.join(timeout=3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(received[-len(payload):], payload)
            fill()
            with self.assertRaisesRegex(RuntimeError, '750 ms'): session.write(payload)
            session.status['error'] = 'UDP sender: Connection timed out'
            with self.assertRaisesRegex(RuntimeError, 'UDP sender'): session.write(payload)
        finally:
            pipe.close(); os.close(read_fd)

    def test_masked_pcm_and_ping(self):
        a, b = socket.socketpair()
        try:
            payload = bytes(bytearray(range(256))) * 8
            a.sendall(masked(2, payload))
            self.assertEqual(m.receive_frame(b), (2, payload))
            a.sendall(masked(9, b'test'))
            self.assertEqual(m.receive_frame(b), (9, b'test'))
        finally: a.close(); b.close()

    def test_reject_unmasked_fragmented_and_oversized(self):
        for frame in (b'\x82\x00', b'\x02\x80', b'\x82\xff' + struct.pack('!Q', 1000000), b'\x89\xfe'):
            a, b = socket.socketpair()
            try:
                a.sendall(frame)
                with self.assertRaises(ValueError): m.receive_frame(b)
            finally: a.close(); b.close()

    def test_admission_validation_does_not_spawn(self):
        manager = m.Manager({'rooms': [ROOM]})
        for change in ({'room': 'Unknown'}, {'rate': 48000}, {'volume': 101}, {'volume': True}, {'muted': 'false'}):
            request = dict(START); request.update(change)
            with mock.patch.object(m.Session, 'start') as start:
                with self.assertRaises(ValueError): manager.create(request)
                start.assert_not_called()

    def test_authenticated_stream_ready_cleanup_and_busy(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = os.path.join(directory, 'worker')
            with open(worker, 'w') as stream:
                stream.write('''#!/usr/bin/env python3
import json, os, sys
print(json.dumps({'type':'ready'})); sys.stdout.flush()
total=0
while True:
    data=os.read(0,4096)
    if not data: break
    total+=len(data)
    print(json.dumps({'type':'stats','received_bytes':total})); sys.stdout.flush()
''')
            os.chmod(worker, 0o700)
            config = {'bind': '127.0.0.1', 'allowed_clients': ['127.0.0.1'], 'token': 'x' * 32,
                      'worker': worker, 'helper_config': 'unused', 'rooms': [ROOM],
                      'log': os.path.join(directory, 'log'), 'status_file': os.path.join(directory, 'status')}
            manager = m.Manager(config)
            server = m.Server(('127.0.0.1', 0), manager)
            thread = threading.Thread(target=server.serve_forever); thread.daemon = True; thread.start()
            def connect(token, origin=False):
                sock = socket.create_connection(server.server_address, 3)
                request = 'GET /v1/intercom HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: ' + base64.b64encode(b'0123456789abcdef').decode() + '\r\nAuthorization: Bearer ' + token + '\r\n'
                if origin: request += 'Origin: http://example.test\r\n'
                sock.sendall((request + '\r\n').encode())
                header = b''
                while not header.endswith(b'\r\n\r\n'): header += m.exact(sock, 1)
                return sock, header
            try:
                for token, origin in [('wrong', False), (config['token'], True)]:
                    sock, header = connect(token, origin)
                    self.assertIn(b'403', header); sock.close()
                    self.assertFalse(manager.sessions)
                sock, header = connect(config['token'])
                self.assertIn(b'101', header)
                sock.sendall(masked(1, json.dumps(START).encode()))
                self.assertEqual(incoming(sock)[1]['type'], 'preparing')
                self.assertEqual(incoming(sock)[1]['type'], 'ready')
                sock.sendall(masked(9, b'ping'))
                self.assertEqual(incoming(sock), (10, b'ping'))
                sock.sendall(masked(2, b'\1\0\1\0' * 1004))
                deadline = time.time() + 3
                while time.time() < deadline:
                    if manager.snapshot()['sessions'][0]['received_bytes'] == 4016: break
                    time.sleep(.02)
                self.assertEqual(manager.snapshot()['sessions'][0]['received_bytes'], 4016)
                with self.assertRaises(ValueError): manager.create(START)
                sock.close()  # Abrupt disconnect must close worker and release admission.
                deadline = time.time() + 3
                while manager.sessions and time.time() < deadline: time.sleep(.02)
                self.assertFalse(manager.sessions)
                self.assertEqual(manager.recent[0]['state'], 'closed')
                # The specific native failure must reach both client and status;
                # a promotion timeout is not a stopped/standalone admission error.
                reason = 'Speaker setup failed: timed out waiting for receiver/helper separation'
                with open(worker, 'w') as stream:
                    stream.write('#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps(' + repr({'type': 'error', 'message': reason}) + ')); sys.stdout.flush()\nsys.exit(7)\n')
                sock, header = connect(config['token'])
                sock.sendall(masked(1, json.dumps(START).encode()))
                self.assertEqual(incoming(sock)[1]['type'], 'preparing')
                self.assertEqual(incoming(sock)[1], {'type': 'error', 'message': reason})
                sock.close()
                deadline = time.time() + 3
                while manager.sessions and time.time() < deadline: time.sleep(.02)
                self.assertFalse(manager.sessions)
                self.assertEqual(manager.recent[-1]['error'], reason)
                self.assertEqual(manager.recent[-1]['exit_code'], 7)
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
