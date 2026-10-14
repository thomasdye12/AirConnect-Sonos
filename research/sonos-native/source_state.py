"""Offline decoder for canonical CurrentSourceState strings; no device calls.

Layout recovered from Play:3 86.10-81100 serializer 0x102f0968, parser
0x102f0bac and descriptor routines 0x1070a68c/0x1070a818. Field names are
object offsets, NOT inferred semantics. Decoding does not validate a playable
source or provide a way to establish a UDP receiver.
"""
import argparse
import json
from pathlib import Path
import re

WIDTHS = (4, 8, 8, 8, 4, 2, 8, 8, 8, 8, 8, 8, 8, 8, 2)
OFFSETS = ('0x00ea', '0x00f0', '0x0138', '0x013c', '0x0140',
           '0x0154', '0x0144', '0x0148', '0x0124', '0x0128',
           '0x014c', '0x0150', '0x012c', '0x0130', '0x0120')


def decode_descriptor(text):
    """Decode the canonical 64-character descriptor, including space padding.

    Flags 0..3 select an optional (u32, u32, u64) block and an optional
    (8 bytes, u16, u16) block. Meanings of these values remain unverified.
    The firmware's scanf parser is more permissive; this deliberately accepts
    only the serializer's fixed-width shape.
    """
    if len(text) != 64 or not re.match(r'^0[0-3]:', text):
        raise ValueError('Expected a 64-character descriptor with flags 00..03')
    flags = int(text[:2], 16)
    cursor = 3
    result = dict(flags=flags)
    if flags & 1:
        match = re.match(r'([0-9A-Fa-f]{8}):([0-9A-Fa-f]{8}):([0-9A-Fa-f]{16}):', text[cursor:])
        if not match:
            raise ValueError('Invalid descriptor block 1')
        result['block_1'] = [int(v, 16) for v in match.groups()]
        cursor += 35
    if flags & 2:
        match = re.match(r'([0-9A-Fa-f]{16}):([0-9A-Fa-f]{4}):([0-9A-Fa-f]{4})', text[cursor:])
        if not match:
            raise ValueError('Invalid descriptor block 2')
        data, first, second = match.groups()
        result['block_2'] = dict(bytes=list(bytes.fromhex(data)), u16=[int(first, 16), int(second, 16)])
        cursor += 26
    if text[cursor:] != ' ' * (64 - cursor):
        raise ValueError('Descriptor padding must consist of spaces')
    return result


def decode_source_state(text):
    if not isinstance(text, str) or len(text) != 164:
        raise ValueError('CurrentSourceState must contain exactly 164 characters')
    if not re.fullmatch(r'[0-9A-Fa-f]{100}', text[:100]):
        raise ValueError('Source-state prefix must contain 100 hexadecimal characters')
    cursor, fields = 0, {}
    for offset, width in zip(OFFSETS, WIDTHS):
        fields[offset] = int(text[cursor:cursor + width], 16)
        cursor += width
    return dict(raw_fields_by_object_offset=fields,
                effective_field_0x0120=fields['0x0120'] if fields['0x0120'] <= 0x11 else 0,
                format_descriptor=decode_descriptor(text[100:]),
                playable_source_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path, help='Private text file containing one source-state value')
    args = parser.parse_args()
    # Preserve descriptor space padding; accept only one optional final newline.
    text = args.file.read_text()
    if text.endswith('\n'): text = text[:-1]
    print(json.dumps(decode_source_state(text), indent=2))


if __name__ == '__main__':
    main()
