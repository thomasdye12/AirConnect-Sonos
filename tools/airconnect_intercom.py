#!/usr/bin/env python3
"""Authenticated PCM WebSocket input for native Sonos. Python 3.4+, no dependencies."""
import argparse
import base64
import binascii
import hashlib
import hmac
import ipaddress
import json
import os
import select
import signal
import socket
import struct
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

MAX_FRAME = 65536
RATE_BYTES = 44100 * 4
GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


def exact(sock, count):
    data = bytearray()
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise EOFError('Input disconnected')
        data.extend(chunk)
    return bytes(data)


def receive_frame(sock):
    first, second = struct.unpack('BB', exact(sock, 2))
    opcode, length = first & 15, second & 127
    if first & 112 or not first & 128 or not second & 128 or opcode not in (1, 2, 8, 9, 10):
        raise ValueError('Expected a masked, unfragmented text/binary/control frame')
    if opcode >= 8 and length > 125:
        raise ValueError('Invalid control frame')
    if length == 126:
        length = struct.unpack('!H', exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack('!Q', exact(sock, 8))[0]
    if length > MAX_FRAME:
        raise ValueError('Audio frame exceeds 64 KiB')
    mask = exact(sock, 4)
    raw = exact(sock, length)
    return opcode, bytes(bytearray(value ^ mask[index % 4] for index, value in enumerate(bytearray(raw))))


def send_frame(sock, opcode, payload):
    if len(payload) < 126:
        header = struct.pack('BB', 128 | opcode, len(payload))
    else:
        header = struct.pack('!BBH', 128 | opcode, 126, len(payload))
    sock.sendall(header + payload)


def send_json(sock, data):
    send_frame(sock, 1, json.dumps(data).encode('utf-8'))


def load_config(path):
    with open(path) as stream:
        config = json.load(stream)
    ipaddress.IPv4Address(config['bind'])
    if not 1024 <= int(config.get('port', 8089)) <= 65535:
        raise ValueError('Invalid port')
    for address in config['allowed_clients']:
        ipaddress.IPv4Address(address)
    with open(config['token_file']) as stream:
        config['token'] = stream.read().strip()
    if len(config['token']) < 32:
        raise ValueError('Intercom token must contain at least 32 characters')
    import re
    names, ids = set(), set()
    for room in config['rooms']:
        ipaddress.IPv4Address(room['address'])
        if not re.match(r'^RINCON_[0-9A-F]{17}$', room['uuid']) or not room['name']:
            raise ValueError('Invalid room identity')
        if room['uuid'] in ids or room['name'].lower() in names:
            raise ValueError('Duplicate room')
        ids.add(room['uuid']); names.add(room['name'].lower())
    return config


class Session:
    def __init__(self, manager, room, volume, muted):
        self.manager, self.room = manager, room
        self.lock = threading.Lock()
        self.status = {'room': room['name'], 'uuid': room['uuid'], 'address': room['address'],
                       'state': 'preparing', 'started_at': time.time(), 'volume': volume, 'muted': muted,
                       'received_bytes': 0, 'worker_pid': None}
        self.ready = threading.Event()
        self.process = None
        self.closed = False

    def start(self):
        c = self.manager.config
        command = [c['worker'], c['helper_config'], c['bind'],
                   'http://' + self.room['address'] + ':1400/xml/device_description.xml',
                   'uuid:' + self.room['uuid'], str(self.status['volume']), str(int(self.status['muted']))]
        with open(c['log'], 'ab', buffering=0) as log:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=log, bufsize=0, close_fds=True)
        os.set_blocking(self.process.stdin.fileno(), False) if hasattr(os, 'set_blocking') else self.nonblocking()
        self.status['worker_pid'] = self.process.pid
        thread = threading.Thread(target=self.monitor)
        thread.daemon = True
        thread.start()

    def nonblocking(self):
        import fcntl
        fd = self.process.stdin.fileno()
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)

    def monitor(self):
        try:
            for raw in iter(self.process.stdout.readline, b''):
                if len(raw) > 2048:
                    continue
                message = json.loads(raw.decode('utf-8'))
                with self.lock:
                    if message['type'] == 'ready':
                        self.status['state'] = 'ready'
                        self.ready.set()
                    elif message['type'] in ('stats', 'closed'):
                        self.status.update({k: v for k, v in message.items() if k != 'type'})
                    elif message['type'] == 'error':
                        self.status['error'] = str(message.get('message', 'Native sender failed'))[:512]
                self.manager.publish()
        except (OSError, ValueError, KeyError):
            pass
        finally:
            self.process.wait()
            with self.lock:
                self.status['state'] = 'closed'
                self.status['exit_code'] = self.process.returncode
            self.ready.set()
            self.manager.publish()

    def write(self, data):
        # Reject congestion rather than accumulating stale speech in Python.
        view = memoryview(data)
        deadline = time.monotonic() + .1
        while view:
            if self.process.poll() is not None:
                raise RuntimeError('Native sender stopped')
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.process.stdin], [], remaining)[1]:
                raise RuntimeError('PCM input congested')
            try:
                count = os.write(self.process.stdin.fileno(), view)
                view = view[count:]
            except BlockingIOError:
                continue

    def snapshot(self):
        with self.lock:
            return dict(self.status)

    def close(self):
        if self.closed:
            return
        self.closed = True
        with self.lock:
            self.status['state'] = 'restoring'
        self.manager.publish()
        if self.process:
            self.process.stdin.close()
            # Signal cancels a still-pending setup/lease wait as well as playback.
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=25)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
                with self.lock:
                    self.status['error'] = 'Sender did not exit; speaker restoration unverified'
            self.process.stdout.close()
        with self.lock:
            self.status['state'] = 'closed'
            self.status['ended_at'] = time.time()
        self.manager.remove(self)


class Manager:
    def __init__(self, config):
        self.config = config
        self.lock = threading.RLock()
        self.sessions, self.recent = {}, []

    def create(self, request):
        if request.get('type') != 'start' or request.get('format') != 's16le' or request.get('rate') != 44100 or request.get('channels') != 2:
            raise ValueError('Start requires s16le, rate 44100, channels 2')
        name = request.get('room')
        if not isinstance(name, str):
            raise ValueError('Room is required')
        room = next((r for r in self.config['rooms'] if name.lower() in (r['name'].lower(), r['uuid'].lower())), None)
        if not room:
            raise ValueError('Room is not configured for intercom')
        volume = request.get('volume', 35)
        muted = request.get('muted', False)
        if type(volume) is not int or not 0 <= volume <= self.config.get('max_volume', 100) or type(muted) is not bool:
            raise ValueError('Invalid volume/mute')
        with self.lock:
            if room['uuid'] in self.sessions or len(self.sessions) >= 4:
                raise ValueError('Room busy or session limit reached')
            session = Session(self, room, volume, muted)
            self.sessions[room['uuid']] = session
        try:
            session.start()
        except Exception:
            session.close()
            raise
        self.publish()
        return session

    def snapshot(self):
        with self.lock:
            return {'updated_at': time.time(), 'sessions': [s.snapshot() for s in self.sessions.values()],
                    'recent': self.recent[-10:]}

    def publish(self):
        with self.lock:
            path = self.config['status_file']
            temporary = path + '.new'
            try:
                with open(temporary, 'w') as stream:
                    json.dump(self.snapshot(), stream)
                os.chmod(temporary, 0o644)
                os.replace(temporary, path)
            except OSError:
                pass

    def remove(self, session):
        with self.lock:
            self.sessions.pop(session.room['uuid'], None)
            self.recent.append(session.snapshot())
            self.recent = self.recent[-10:]
        self.publish()


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, manager):
        self.manager = manager
        self.slots = threading.BoundedSemaphore(12)
        HTTPServer.__init__(self, address, Handler)

    def process_request(self, request, address):
        request.settimeout(3)
        if address[0] not in self.manager.config['allowed_clients'] or not self.slots.acquire(False):
            self.shutdown_request(request)
            return
        try:
            ThreadingMixIn.process_request(self, request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            ThreadingMixIn.process_request_thread(self, request, address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    rbufsize = 0  # No hidden prefetched WebSocket bytes outside select().
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_GET(self):
        c = self.server.manager.config
        authorization = self.headers.get('Authorization', '').encode('utf-8')
        if self.headers.get('Origin') or not hmac.compare_digest(authorization, ('Bearer ' + c['token']).encode('utf-8')):
            self.send_error(403)
            return
        if self.path == '/v1/status':
            body = json.dumps(self.server.manager.snapshot()).encode('utf-8')
            self.send_response(200); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body))); self.end_headers()
            self.wfile.flush(); self.connection.sendall(body)
            return
        key = self.headers.get('Sec-WebSocket-Key', '')
        try:
            valid_key = len(base64.b64decode(key.encode('ascii'), validate=True)) == 16
        except (ValueError, UnicodeError, binascii.Error):
            valid_key = False
        if self.path != '/v1/intercom' or not valid_key or self.headers.get('Sec-WebSocket-Version') != '13' or self.headers.get('Upgrade', '').lower() != 'websocket' or 'upgrade' not in self.headers.get('Connection', '').lower().split(', '):
            self.send_error(400)
            return
        self.send_response(101)
        self.send_header('Upgrade', 'websocket'); self.send_header('Connection', 'Upgrade')
        self.send_header('Sec-WebSocket-Accept', base64.b64encode(hashlib.sha1((key + GUID).encode('ascii')).digest()).decode('ascii'))
        self.end_headers(); self.wfile.flush()
        session = None
        try:
            opcode, data = receive_frame(self.connection)
            if opcode != 1 or len(data) > 4096:
                raise ValueError('Send a start message first')
            request = json.loads(data.decode('utf-8'))
            if not isinstance(request, dict):
                raise ValueError('Invalid start message')
            session = self.server.manager.create(request)
            send_json(self.connection, {'type': 'preparing', 'room': session.room['name']})
            deadline = time.monotonic() + 40
            while not session.ready.wait(.1):
                if time.monotonic() > deadline:
                    raise RuntimeError('Speaker preparation timed out')
                if select.select([self.connection], [], [], 0)[0]:
                    opcode, data = receive_frame(self.connection)
                    if opcode == 8:
                        return
                    if opcode == 9:
                        send_frame(self.connection, 10, data)
                    elif opcode != 10:
                        raise ValueError('Wait for ready before sending PCM')
            if session.process.poll() is not None or session.snapshot()['state'] != 'ready':
                state = session.snapshot()
                raise RuntimeError(state.get('error') or 'Speaker setup failed (worker exit {}); check intercom log'.format(state.get('exit_code')))
            send_json(self.connection, {'type': 'ready', 'room': session.room['name'], 'rate': 44100, 'channels': 2, 'format': 's16le'})
            started = last_input = time.monotonic()
            budget, budget_at = RATE_BYTES, started
            while time.monotonic() - started < 600:
                if session.process.poll() is not None:
                    raise RuntimeError(session.snapshot().get('error') or 'Native sender stopped')
                if time.monotonic() - last_input > 15:
                    raise RuntimeError('Input heartbeat timed out')
                if not select.select([self.connection], [], [], .5)[0]:
                    continue
                opcode, data = receive_frame(self.connection)
                last_input = time.monotonic()
                if opcode == 8:
                    send_frame(self.connection, 8, data)
                    break
                if opcode == 9:
                    send_frame(self.connection, 10, data)
                elif opcode == 2:
                    if not data or len(data) % 4:
                        raise ValueError('PCM must contain complete stereo frames')
                    now = time.monotonic()
                    budget = min(RATE_BYTES, budget + (now - budget_at) * RATE_BYTES * 1.1)
                    budget_at = now
                    budget -= len(data)
                    if budget < 0:
                        raise ValueError('PCM exceeds live audio rate')
                    session.write(data)
                elif opcode != 10:
                    raise ValueError('Expected binary PCM')
        except (OSError, EOFError, ValueError, RuntimeError) as exc:
            if session:
                with session.lock:
                    session.status['error'] = str(exc)
            try:
                send_json(self.connection, {'type': 'error', 'message': str(exc)})
                send_frame(self.connection, 8, struct.pack('!H', 1011))
            except OSError:
                pass
        finally:
            if session:
                session.close()
            self.close_connection = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/var/airplay_sonos/intercom/config.json')
    args = parser.parse_args()
    config = load_config(args.config)
    manager = Manager(config)
    manager.publish()
    def heartbeat():
        while True:
            time.sleep(5)
            manager.publish()
    publisher = threading.Thread(target=heartbeat)
    publisher.daemon = True
    publisher.start()
    server = Server((config['bind'], config.get('port', 8089)), manager)
    def stop(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        with manager.lock:
            sessions = list(manager.sessions.values())
        for session in sessions:
            session.close()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
