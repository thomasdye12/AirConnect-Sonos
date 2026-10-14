#!/usr/bin/env python3
"""Experimental Sonos line-in codec, derived from a single user's capture.
Offline only: this module does not send packets or alter speakers.
"""
import argparse
import collections
import dataclasses
import json
import pathlib
import socket
import struct
import wave

@dataclasses.dataclass
class Datagram:
    time: float
    source: str
    destination: str
    source_port: int
    destination_port: int
    data: bytes


def read_udp(path):
    with open(path, 'rb') as f:
        magic = f.read(4)
        formats = {b'\xd4\xc3\xb2\xa1': ('<', 1e6), b'\xa1\xb2\xc3\xd4': ('>', 1e6),
                   b'\x4d\x3c\xb2\xa1': ('<', 1e9), b'\xa1\xb2\x3c\x4d': ('>', 1e9)}
        if magic not in formats:
            raise ValueError('Expected classic pcap (convert pcapng first)')
        order, scale = formats[magic]
        header = f.read(20)
        if len(header) != 20 or struct.unpack(order+'HHIIII', header)[-1] != 1:
            raise ValueError('Expected Ethernet link type')
        while h := f.read(16):
            if len(h) != 16:
                raise ValueError('Truncated pcap record header')
            sec, frac, size, original = struct.unpack(order+'IIII', h)
            if size > 16*1024*1024:
                raise ValueError('Oversized pcap record')
            b = f.read(size)
            if len(b) != size:
                raise ValueError('Truncated pcap record')
            if len(b) < 14:
                continue
            off = 14
            typ = int.from_bytes(b[12:14], 'big')
            while typ in (0x8100, 0x88a8) and len(b) >= off+4:
                typ = int.from_bytes(b[off+2:off+4], 'big'); off += 4
            if typ != 0x0800 or len(b) < off+20:
                continue
            ip = b[off:]
            ih = (ip[0]&15)*4
            if ip[0] >> 4 != 4 or ih < 20 or len(ip) < ih or ip[9] != 17:
                continue
            if int.from_bytes(ip[6:8], 'big') & 0x3fff:
                raise ValueError('Fragmented UDP requires IP reassembly')
            length = int.from_bytes(ip[2:4], 'big')
            if len(ip) < length:
                raise ValueError('Truncated IP packet')
            d = ip[ih:length]
            if len(d) < 8:
                raise ValueError('Short UDP header')
            sp, dp, ul, checksum = struct.unpack('!HHHH', d[:8])
            if ul < 8 or ul > len(d):
                raise ValueError('Invalid UDP length')
            yield Datagram(sec+frac/scale, socket.inet_ntoa(ip[12:16]),
                           socket.inet_ntoa(ip[16:20]), sp, dp, d[8:ul])

@dataclasses.dataclass
class AudioPacket:
    sequence: int
    seconds: int
    microseconds: int
    byte_position: int
    pcm: bytes
    omitted_zeros: int = 0

    @classmethod
    def decode(cls, data):
        # Sonos omits trailing zero bytes; the logical record length remains 1008.
        if len(data) < 28 or len(data) > 1032:
            raise ValueError('Not a supported audio packet')
        if data[:2] != b'\x00\x02' or data[4:12] != bytes.fromhex('03000000010003f0'):
            raise ValueError('Unknown audio framing')
        if data[24:28] != bytes.fromhex('0210ac44'):
            raise ValueError('Only observed 44.1kHz / 16-bit / stereo format supported')
        sec, us, position = struct.unpack('!III', data[12:24])
        if us >= 1000000:
            raise ValueError('Invalid timestamp fraction')
        pcm = data[28:].ljust(1004, b'\0')
        return cls(int.from_bytes(data[2:4], 'big'), sec, us, position, pcm, 1032-len(data))

    def encode(self):
        if len(self.pcm) != 1004 or not 0 <= self.microseconds < 1000000:
            raise ValueError('Expected 251 stereo frames and a valid timestamp')
        head = b'\x00\x02' + struct.pack('!H', self.sequence) + bytes.fromhex('03000000010003f0')
        head += struct.pack('!III', self.seconds, self.microseconds, self.byte_position)
        head += bytes.fromhex('0210ac44')
        return (head + self.pcm).rstrip(b'\0')


def decode_capture(path, output, source, destination):
    output = pathlib.Path(output); output.mkdir(parents=True, exist_ok=True)
    stats = collections.Counter(); segments = []; current = []; previous = None; first = None
    timestamp_errors = []; sequence_errors = []; last_sequence = None
    for d in read_udp(path):
        if d.source != source or d.destination != destination or d.destination_port != 7020:
            continue
        if first is None: first = d.time
        stats['udp_packets'] += 1
        if len(d.data) >= 4:
            seq = int.from_bytes(d.data[2:4], 'big')
            if last_sequence is not None and seq != (last_sequence+1)&65535:
                sequence_errors.append([last_sequence, seq])
            last_sequence = seq
        if len(d.data) < 28:
            stats['short_control_packets'] += 1
            continue
        p = AudioPacket.decode(d.data)
        if p.encode() != d.data:
            raise ValueError('Packet does not round-trip exactly')
        stats['audio_packets'] += 1
        stats['trailing_zero_bytes_restored'] += p.omitted_zeros
        stats['exact_roundtrips'] += 1
        new_segment = previous is None or p.byte_position < previous.byte_position
        if new_segment:
            if current: segments.append(current)
            current = []
        elif p.byte_position != previous.byte_position + len(previous.pcm):
            raise ValueError('Audio byte position gap; refusing to concatenate missing samples')
        else:
            delta = (p.seconds-previous.seconds)*1000000+p.microseconds-previous.microseconds
            timestamp_errors.append(abs(delta-251/44100*1e6))
        current.append((d.time-first, p)); previous = p
    if current: segments.append(current)
    if not segments: raise ValueError('No matching audio packets')
    results = []
    for i, frames in enumerate(segments, 1):
        name = 'segment-%02d.wav' % i
        with wave.open(str(output/name), 'wb') as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
            w.writeframes(b''.join(p.pcm for t,p in frames))
        results.append({'file': name, 'packets': len(frames),
                        'audio_seconds': len(frames)*251/44100,
                        'capture_start_seconds': frames[0][0],
                        'capture_end_seconds': frames[-1][0],
                        'first_byte_position': frames[0][1].byte_position})
    report = {'counts': dict(stats), 'segments': results, 'sequence_discontinuities': sequence_errors,
              'max_timestamp_step_error_us': max(timestamp_errors, default=0),
              'limitations': ['Derived from one capture and firmware combination.',
                              'WAV audio interpretation is inferred; listening validation required.',
                              'No latency or speaker acceptance claim.']}
    (output/'decode-report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture'); p.add_argument('--output', required=True)
    p.add_argument('--source', required=True); p.add_argument('--destination', required=True)
    a = p.parse_args()
    print(json.dumps(decode_capture(a.capture, a.output, a.source, a.destination), indent=2))
