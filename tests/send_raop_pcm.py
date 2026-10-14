#!/usr/bin/env python3
"""Bounded synthetic AirPlay 1 sender for an explicitly selected test receiver.
Sends unencrypted ALAC, RTP sync and NTP replies. Default volume is mute.
This is a protocol test, not an iPhone compatibility or acoustic latency result.
"""
import argparse
import math
import re
import socket
import struct
import threading
import time


def ntp():
    value = time.time() + 2208988800
    whole = int(value)
    return struct.pack('!II', whole, int((value - whole) * (1 << 32)))


def alac(index, tone, frequency=440):
    # Stereo, no optional-size word, no low bytes, uncompressed samples.
    bits = (1 << 20) | 1
    for i in range(352):
        sample = int(3000 * math.sin(2 * math.pi * frequency * (index * 352 + i) / 44100)) if tone else 0
        bits = (bits << 32) | ((sample & 65535) << 16) | (sample & 65535)
    bits = (bits << 3) | 7  # ALAC end element
    bit_count = 23 + 352 * 32 + 3
    pad = (-bit_count) % 8
    return (bits << pad).to_bytes((bit_count + pad) // 8, 'big')


def run(a):
    stop = threading.Event()
    timing = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    audio = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    timing.bind((a.local, 0)); timing.settimeout(.1)
    control.bind((a.local, 0)); audio.bind((a.local, 0))
    def clock():
        while not stop.is_set():
            try: data, peer = timing.recvfrom(2048)
            except socket.timeout: continue
            if len(data) == 32:
                timing.sendto(b'\x80\xd3\x00\x07' + bytes(4) + data[24:32] + ntp() + ntp(), peer)
    thread = threading.Thread(target=clock); thread.start()
    conn = socket.create_connection((a.host, a.port), timeout=20)
    stream = conn.makefile('rb')
    seq = 0
    def rtsp(method, headers=None, body=b''):
        nonlocal seq
        seq += 1
        values = {'CSeq': str(seq), 'User-Agent': 'AirConnect native validation', 'X-Apple-Client-Name': 'Native test sender', 'Content-Length': str(len(body))}
        values.update(headers or {})
        conn.sendall((method + ' rtsp://' + a.host + '/native-test RTSP/1.0\r\n' + ''.join(k + ': ' + v + '\r\n' for k, v in values.items()) + '\r\n').encode() + body)
        status = stream.readline().decode().strip()
        response = {}
        while True:
            line = stream.readline().decode().strip()
            if not line: break
            k, v = line.split(':', 1); response[k.lower()] = v.strip()
        stream.read(int(response.get('content-length', 0)))
        if '200' not in status: raise RuntimeError(method + ': ' + status)
        return response
    try:
        sdp = ('v=0\r\no=AirConnect 1 0 IN IP4 ' + a.local + '\r\ns=Native test\r\nc=IN IP4 ' + a.host + '\r\nt=0 0\r\nm=audio 0 RTP/AVP 96\r\na=rtpmap:96 AppleLossless\r\na=fmtp:96 352 0 16 40 10 14 2 255 0 0 44100\r\n').encode()
        rtsp('ANNOUNCE', {'Content-Type': 'application/sdp'}, sdp)
        response = rtsp('SETUP', {'Transport': 'RTP/AVP/UDP;unicast;mode=record;control_port=%d;timing_port=%d' % (control.getsockname()[1], timing.getsockname()[1])})
        transport = dict(re.findall(r'(\w+_port)=(\d+)', response['transport']))
        aport, cport = int(transport['server_port']), int(transport['control_port'])
        number, stamp = 1000, 352000
        rtsp('SET_PARAMETER', {'Content-Type': 'text/parameters'}, ('volume: %s\r\n' % a.volume).encode())
        record = rtsp('RECORD', {'RTP-Info': 'seq=%d;rtptime=%d' % (number, stamp)})
        receiver_delay = int(record.get('audio-latency', 0)) / 44100
        source_delay = a.latency_ms * 44100 // 1000
        count = int(a.seconds * 44100 / 352)
        base = time.monotonic(); paused = False
        for i in range(count):
            if a.flush_at and i * 352 / 44100 >= a.flush_at and not paused:
                rtsp('FLUSH', {'RTP-Info': 'seq=%d;rtptime=%d' % (number, stamp)})
                time.sleep(2); base += 2; paused = True
            if i % 50 == 0:
                control.sendto(b'\x90\xd4\x00\x07' + struct.pack('!I', (stamp - source_delay) & 0xffffffff) + ntp() + struct.pack('!I', stamp), (a.host, cport))
            packet = struct.pack('!BBHII', 0x80, 0xe0 if i == 0 else 0x60, number, stamp, 1) + alac(i, a.tone, a.frequency)
            audio.sendto(packet, (a.host, aport))
            number = (number + 1) & 65535; stamp = (stamp + 352) & 0xffffffff
            wait = base + (i + 1) * 352 / 44100 - time.monotonic()
            if wait > 0: time.sleep(wait)
        time.sleep(a.latency_ms / 1000 + receiver_delay + .1)
        if not a.disconnect:
            rtsp('TEARDOWN')
        print('AirPlay RTP complete: %d frames; flush/resume=%s' % (count, paused), flush=True)
    finally:
        stream.close(); conn.close(); stop.set(); thread.join()
        timing.close(); control.close(); audio.close()

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', required=True); p.add_argument('--port', type=int, required=True)
    p.add_argument('--local', default='127.0.0.1'); p.add_argument('--seconds', type=int, default=20, choices=range(1, 121))
    p.add_argument('--latency-ms', type=int, default=2000, choices=range(0, 5001))
    p.add_argument('--flush-at', type=int, default=0); p.add_argument('--tone', action='store_true')
    p.add_argument('--disconnect', action='store_true', help='Close TCP without TEARDOWN to test cleanup')
    p.add_argument('--frequency', type=int, choices=(440, 660), default=440)
    p.add_argument('--volume', type=float, default=-144, choices=[-144, -30, -25, -20, -15])
    run(p.parse_args())
