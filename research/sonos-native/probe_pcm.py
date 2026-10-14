"""Deterministic, quiet PCM for bounded receiver experiments.

Samples are stereo signed 16-bit little endian, at 44.1 kHz. A nonzero
signal can be sent with the speaker muted to exercise real payload sizes.
"""
import math
import struct

RATE = 44100
FRAMES = 251


def pcm_packet(index, packet_count, signal='silence'):
    if signal not in ('silence', 'tone'):
        raise ValueError('Unknown PCM signal')
    if not 0 <= index < packet_count:
        raise ValueError('Packet index outside the bounded signal')
    if signal == 'silence':
        return bytes(FRAMES * 4)
    total_frames = packet_count * FRAMES
    samples = bytearray(FRAMES * 4)
    for j in range(FRAMES):
        frame = index * FRAMES + j
        envelope = min(1, frame / (RATE * .2),
                       (total_frames - 1 - frame) / (RATE * .2))
        value = round(6000 * envelope * math.sin(2 * math.pi * 440 * frame / RATE))
        struct.pack_into('<hh', samples, j * 4, value, value)
    return bytes(samples)
