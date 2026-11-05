"""Concurrent loopback tests; never contacts or configures a Sonos speaker.

Build native/ with make first. SONOS_NATIVE_LIBRARY can select another build.
"""
import concurrent.futures
import os
from pathlib import Path
import socket
import sys
import unittest

from linein import AudioPacket
from native_sender import NativeSender

LIBRARY = os.environ.get('SONOS_NATIVE_LIBRARY', str(
    Path(__file__).parent / 'native' / 'build' /
    ('libsonos_native.dylib' if sys.platform == 'darwin' else 'libsonos_native.so')))


class NativeSessions(unittest.TestCase):
    def test_independent_audio_clocks_and_close(self):
        senders, receivers = [], []
        try:
            for _ in range(8):
                rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                receivers.append(rx)
                rx.bind(('127.0.0.1', 0))
                rx.settimeout(2)
                senders.append(NativeSender(LIBRARY, '127.0.0.1', '127.0.0.1',
                                            audio_port=rx.getsockname()[1]))
            self.assertEqual(len({s.clock_port for s in senders}), 8)

            def round_trip(i, packet_count, first_sequence):
                sender, rx = senders[i], receivers[i]
                # Different nonzero PCM for every stream; split mid-sample/packet.
                block = bytes(((j + 29 * i) % 255) + 1 for j in range(1004))
                payload = block * packet_count
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as clock:
                    clock.settimeout(2)
                    clock.connect(('127.0.0.1', sender.clock_port))
                    request = bytearray(48)
                    request[0] = 0x1b
                    token = bytes([i + 1, first_sequence]) * 4
                    request[40:48] = token
                    clock.send(request)
                    response = clock.recv(512)
                    self.assertEqual(len(response), 48)
                    self.assertEqual(response[24:32], token)
                for offset in range(0, len(payload), 137):
                    sender.write(payload[offset:offset + 137])
                timestamps = []
                for n in range(packet_count):
                    decoded = AudioPacket.decode(rx.recv(4096))
                    self.assertEqual(decoded.pcm, block)
                    self.assertEqual(decoded.sequence, 0x20000 + first_sequence + n)
                    self.assertEqual(decoded.byte_position, (first_sequence + n) * 1004)
                    timestamps.append(decoded.seconds * 1000000 + decoded.microseconds)
                self.assertTrue(all(a < b for a, b in zip(timestamps, timestamps[1:])))

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                # All eight producers run at once, with independent clocks/state.
                jobs = [pool.submit(round_trip, i, 20, 0) for i in range(8)]
                for job in jobs:
                    job.result(timeout=5)
                senders[0].close()
                with self.assertRaises(RuntimeError):
                    senders[0].write(b'\0' * 1004)
                # Closing one must not stop or reset the surviving sessions.
                jobs = [pool.submit(round_trip, i, 10, 20) for i in range(1, 8)]
                for job in jobs:
                    job.result(timeout=5)
            for sender in senders[1:]:
                stats = sender.stats()
                self.assertEqual(stats['packets'], 30)
                self.assertEqual(stats['clock_requests'], 2)
        finally:
            for sender in senders:
                sender.close()
            for receiver in receivers:
                receiver.close()


if __name__ == '__main__':
    unittest.main()
