"""Experimental bounded Sonos local API client; not part of the production bridge.
Wire format reference: https://github.com/jjlawren/sonos-websocket
Implemented independently using the Python standard library. Device TLS peer
verification is disabled for this LAN lab client; no account credentials are sent.
"""
import base64
from collections import deque
import hashlib
import json
import os
import socket
import ssl
import struct
import time
import uuid


class LocalAPI:
    def __init__(self, ip, timeout=8):
        self.timeout = timeout
        self.pending = bytearray()
        self.socket = None
        self.household_id = None
        self.counter = 0
        self.events = deque(maxlen=256)
        self.fragment = bytearray()
        self.fragment_started = False
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        raw = socket.create_connection((ip, 1443), timeout=timeout)
        try:
            self.socket = context.wrap_socket(raw, server_hostname=ip)
            self.certificate_sha256 = hashlib.sha256(self.socket.getpeercert(binary_form=True)).hexdigest()
            key = base64.b64encode(os.urandom(16)).decode()
            request = (f'GET /websocket/api HTTP/1.1\r\nHost: {ip}:1443\r\n'
                       'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                       f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n'
                       'Sec-WebSocket-Protocol: v1.api.smartspeaker.audio\r\n'
                       f'X-Sonos-Api-Key: {uuid.uuid4()}\r\n\r\n')
            self.socket.sendall(request.encode())
            self.deadline = time.monotonic() + timeout
            while b'\r\n\r\n' not in self.pending:
                self._read_more(4096)
                if len(self.pending) > 65536:
                    raise ValueError('Oversized HTTP header')
            header, tail = bytes(self.pending).split(b'\r\n\r\n', 1)
            self.pending = bytearray(tail)
            self.handshake_status = header.split(b'\r\n')[0].decode()
            if b' 101 ' not in header.split(b'\r\n')[0]:
                raise RuntimeError(self.handshake_status)
            headers = {line.split(b':', 1)[0].lower(): line.split(b':', 1)[1].strip()
                       for line in header.split(b'\r\n')[1:] if b':' in line}
            expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
            if headers.get(b'sec-websocket-accept') != expected:
                raise ValueError('Invalid WebSocket accept key')
            if headers.get(b'sec-websocket-protocol') != b'v1.api.smartspeaker.audio':
                raise ValueError('Unexpected WebSocket protocol')
        except BaseException:
            self.close()
            raw.close()
            raise

    def _read_more(self, n):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Local API deadline')
        self.socket.settimeout(remaining)
        data = self.socket.recv(min(65536, n))
        if not data:
            raise EOFError('Local API closed')
        self.pending.extend(data)

    def _ensure(self, n):
        while len(self.pending) < n:
            self._read_more(n - len(self.pending))

    def _frame(self):
        # Consume only complete frames, so a polling timeout is resumable even
        # if it occurs between header bytes or halfway through the payload.
        self._ensure(2)
        first, second = self.pending[:2]
        opcode = first & 15
        if first & 0x70 or second & 0x80:
            raise ValueError('Unsupported server frame flags')
        n = second & 127
        offset = 2
        if n in (126, 127):
            width = 2 if n == 126 else 8
            self._ensure(2 + width)
            n = int.from_bytes(self.pending[2:2 + width], 'big')
            offset += width
        if n > 4 * 1024 * 1024:
            raise ValueError('Oversized frame')
        if opcode >= 8 and (n > 125 or not first & 128):
            raise ValueError('Invalid control frame')
        self._ensure(offset + n)
        data = bytes(self.pending[offset:offset + n])
        del self.pending[:offset + n]
        return first, opcode, data

    def _send(self, payload, opcode=1):
        mask = os.urandom(4)
        n = len(payload)
        if n > 65535:
            raise ValueError('Diagnostic request exceeds limit')
        header = bytes([0x80 | opcode, 0x80 | (n if n < 126 else 126)])
        if n >= 126:
            header += struct.pack('!H', n)
        self.socket.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def _receive(self):
        while True:
            first, opcode, data = self._frame()
            if opcode == 8:
                raise EOFError('WebSocket close received')
            if opcode == 9:
                self._send(data, 10)
                continue
            if opcode == 10:
                continue
            if opcode not in (0, 1) or (opcode == 0) != self.fragment_started:
                raise ValueError('Unexpected data frame')
            self.fragment_started = True
            self.fragment.extend(data)
            if len(self.fragment) > 4 * 1024 * 1024:
                raise ValueError('Oversized message')
            if first & 128:
                assembled = self.fragment
                self.fragment = bytearray()
                self.fragment_started = False
                return json.loads(assembled)

    def command(self, namespace, command, options=None, **target):
        self.counter += 1
        cmd_id = 'native-lab-' + str(self.counter)
        self.deadline = time.monotonic() + self.timeout
        self.socket.settimeout(self.timeout)
        self._send(json.dumps([{'namespace': namespace + ':1', 'command': command,
                               'cmdId': cmd_id, **target}, options or {}]).encode())
        while True:
            result = self._receive()
            if not isinstance(result, list) or len(result) != 2 or not isinstance(result[0], dict):
                raise ValueError('Unexpected Sonos response')
            header = result[0]
            if header.get('householdId'):
                self.household_id = header['householdId']
            if header.get('cmdId') == cmd_id:
                return result
            self.events.append(result)

    def receive_event(self, timeout=None):
        """Read one unsolicited message; commands retain intervening events.

        Calls must be serialized by the caller. Raises TimeoutError if no event
        arrives within the requested interval; no command is sent.
        """
        if self.events:
            return self.events.popleft()
        self.deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        return self._receive()

    def close(self):
        if self.socket:
            self.socket.close()
            self.socket = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
