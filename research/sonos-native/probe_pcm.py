"""Deterministic, quiet PCM for bounded receiver experiments.

Samples are stereo signed 16-bit little endian, at 44.1 kHz. A nonzero
signal can be sent with the speaker muted to exercise real payload sizes.
"""
import math
import struct
import wave

RATE = 44100
FRAMES = 251


def load_wav(path, seconds):
    """Read only the bounded test interval; reject incompatible or short files."""
    if not 1 <= seconds <= 120:
        raise ValueError('WAV test duration must be 1..120 seconds')
    count = int(seconds * RATE / FRAMES) * FRAMES
    with wave.open(str(path), 'rb') as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate(), source.getcomptype()) != (2, 2, RATE, 'NONE'):
            raise ValueError('WAV must be uncompressed 44.1 kHz stereo 16-bit PCM')
        pcm = bytearray(source.readframes(count))
    if len(pcm) != count * 4:
        raise ValueError('WAV is shorter than the requested test')
    fade = min(int(RATE * .2), count // 2)
    for edge in range(fade):
        gain = edge / fade
        for frame in (edge, count - 1 - edge):
            left, right = struct.unpack_from('<hh', pcm, frame * 4)
            struct.pack_into('<hh', pcm, frame * 4, round(left * gain), round(right * gain))
    return bytes(pcm)


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
