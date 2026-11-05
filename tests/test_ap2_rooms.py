import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('rooms', Path(__file__).resolve().parents[1] / 'integrations/airplay2/rooms.py')
rooms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rooms)
HELPER = 'RINCON_00000000000101400'
A, B = 'RINCON_00000000000201400', 'RINCON_00000000000301400'


def topology(name='Room', extra=''):
    return '<ZoneGroups><ZoneGroup Coordinator="%s"><ZoneGroupMember UUID="%s" ZoneName="Helper" Location="http://192.0.2.1:1400/xml/device_description.xml"/></ZoneGroup><ZoneGroup Coordinator="%s"><ZoneGroupMember UUID="%s" ZoneName="%s" Location="http://192.0.2.2:1400/xml/device_description.xml">%s</ZoneGroupMember></ZoneGroup></ZoneGroups>' % (HELPER, HELPER, A, A, name, extra)


class RoomTest(unittest.TestCase):
    def test_helper_and_bonded_satellites_not_advertised_separately(self):
        extra = '<Satellite UUID="%s" ZoneName="Room" Invisible="1"/>' % B
        result = rooms.discover(topology(extra=extra), HELPER)
        self.assertEqual([r['uuid'] for r in result], [A])

    def test_stable_identity_and_port_after_rename_and_reordering(self):
        first = rooms.plan(rooms.discover(topology(), HELPER), {}, 32)
        renamed = rooms.plan(rooms.discover(topology('Renamed'), HELPER), first, 32)
        self.assertEqual(first['rooms'][0]['device_id'], renamed['rooms'][0]['device_id'])
        self.assertEqual(first['rooms'][0]['timing_interface'], renamed['rooms'][0]['timing_interface'])
        self.assertEqual(first['rooms'][0]['port'], renamed['rooms'][0]['port'])
        self.assertEqual(renamed['rooms'][0]['advertised_name'], 'Renamed (AirPlay 2)')

    def test_old_port_is_not_reused_for_a_new_room(self):
        first = rooms.plan(rooms.discover(topology(), HELPER), {}, 32)
        room = dict(first['rooms'][0], uuid=B, key=rooms.identity(B))
        second = rooms.plan([room], first, 32)
        self.assertNotEqual(first['rooms'][0]['port'], second['rooms'][0]['port'])

    def test_more_than_sixteen_have_separate_timing_and_ids(self):
        source = rooms.discover(topology(), HELPER)[0]
        entries = [dict(source, uuid='RINCON_%012X01400' % i, key=rooms.identity('RINCON_%012X01400' % i)) for i in range(2, 20)]
        with self.assertRaises(ValueError):
            rooms.plan(entries, {}, 16)
        result = rooms.plan(entries, {}, 32)
        for field in ('port', 'device_id', 'timing_interface'):
            self.assertEqual(len({r[field] for r in result['rooms']}), 18)

    def test_missing_helper_and_untrusted_location_rejected(self):
        with self.assertRaises(ValueError):
            rooms.discover(topology(), B)
        with self.assertRaises(ValueError):
            rooms.discover(topology().replace('192.0.2.2:1400', 'user:password@192.0.2.2:1400'), HELPER)

    def test_configuration_preserves_phone_volume_and_disables_shared_metadata(self):
        r = rooms.plan(rooms.discover(topology('A &quot;Room&quot;'), HELPER), {}, 32)['rooms'][0]
        text = rooms.config(r, '/worker', '/helper.json', '192.0.2.10', 100)
        self.assertIn('speaker_volume = 100;', text)
        self.assertNotIn('ignore_volume_control', text)
        self.assertIn('enabled = "no"', text)
        self.assertIn('A \\"Room\\"', text)


if __name__ == '__main__':
    unittest.main()
