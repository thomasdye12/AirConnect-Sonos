"""Synthetic fixtures from the independently traced field layout; no live data."""
import unittest
from source_state import decode_source_state


class SourceStateTests(unittest.TestCase):
    def fixture(self, descriptor, final=0x11):
        # Deliberately independent of the decoder's field-width table.
        prefix = ('1234' '00000002' '00000003' '00000004' '0005' '06'
                  '00000007' '00000008' '00000009' '0000000A' '0000000B'
                  '0000000C' '0000000D' '0000000E' + format(final, '02X'))
        self.assertEqual(len(prefix), 100)
        return prefix + descriptor.ljust(64)

    def test_field_offsets_and_empty_descriptor(self):
        result = decode_source_state(self.fixture('00:'))
        fields = result['raw_fields_by_object_offset']
        self.assertEqual(fields['0x00ea'], 0x1234)
        self.assertEqual(fields['0x0138'], 3)
        self.assertEqual(fields['0x0154'], 6)
        self.assertEqual(fields['0x0124'], 9)
        self.assertEqual(fields['0x0130'], 14)
        self.assertEqual(result['format_descriptor'], {'flags': 0})
        self.assertFalse(result['playable_source_verified'])

    def test_both_descriptor_blocks(self):
        tail = '03:01234567:89ABCDEF:0123456789ABCDEF:0011223344556677:8899:AABB'
        self.assertEqual(len(tail), 64)
        result = decode_source_state(self.fixture(tail))['format_descriptor']
        self.assertEqual(result['block_1'], [0x01234567, 0x89ABCDEF, 0x0123456789ABCDEF])
        self.assertEqual(result['block_2'], dict(bytes=[0,17,34,51,68,85,102,119], u16=[0x8899,0xAABB]))

    def test_each_optional_block(self):
        a = decode_source_state(self.fixture('01:00000001:00000002:0000000000000003:'))['format_descriptor']
        b = decode_source_state(self.fixture('02:0011223344556677:8899:AABB'))['format_descriptor']
        self.assertNotIn('block_2', a)
        self.assertNotIn('block_1', b)

    def test_parser_enum_clamp_is_reported_without_losing_raw_value(self):
        result = decode_source_state(self.fixture('00:', final=0x12))
        self.assertEqual(result['raw_fields_by_object_offset']['0x0120'], 0x12)
        self.assertEqual(result['effective_field_0x0120'], 0)

    def test_noncanonical_or_truncated_values_rejected(self):
        valid = self.fixture('00:')
        invalid = [valid[:-1], valid + ' ', 'G' + valid[1:],
                   self.fixture('04:'), self.fixture('01:123:'),
                   valid[:-1] + '\x00', valid.rstrip(), self.fixture('00:unexpected')]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_source_state(value)
