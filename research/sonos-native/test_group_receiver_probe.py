"""Offline checks of refusal and rollback; no speaker or network access."""
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import group_receiver_probe as probe

A, B = '192.0.2.10', '192.0.2.11'
UA, UB = 'RINCON_02000000001001400', 'RINCON_02000000001101400'

class FakeSocket:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def connect(self, *args): pass
    def getsockname(self): return ('192.0.2.1', 12345)

class FakeSender:
    clock_port = 12345
    def __init__(self, *args): pass
    def close(self): pass
    def stats(self): return dict(packets=0, clock_requests=0, late_packets=0)
    def write(self, *args): raise AssertionError('Rejected setup must never send PCM')

class Household:
    def __init__(self, playing=False, fail_restore=False):
        self.playing = playing
        self.fail_restore = fail_restore
        self.joined = False
        self.calls = []
        self.uris = {A: 'original-a', B: 'original-b'}
        self.mutes = {A: '0', B: '1'}
    def topology(self):
        root = E.Element('ZoneGroups')
        for ip, uid in ((A, UA), (B, UB)):
            if self.joined and ip == A: continue
            g = E.SubElement(root, 'ZoneGroup', Coordinator=uid, ID=uid + ':1')
            E.SubElement(g, 'ZoneGroupMember', UUID=uid, Location='http://' + ip + ':1400/xml/device_description.xml')
            if self.joined and ip == B:
                E.SubElement(g, 'ZoneGroupMember', UUID=UA, Location='http://' + A + ':1400/xml/device_description.xml')
        return E.tostring(root).decode()
    def call(self, ip, path, service, name, args):
        self.calls.append((ip, name, args.copy()))
        if name == 'ChangeTransportSettings': return {'http_status': 500, 'xml': '<error>800</error>'}
        if name == 'SetAVTransportURI':
            if self.fail_restore and ip == A and args['CurrentURI'] == 'original-a': raise OSError('simulated restore failure')
            self.uris[ip] = args['CurrentURI']
            if args['CurrentURI'].startswith('x-rincon:'): self.joined = True
        elif name == 'BecomeCoordinatorOfStandaloneGroup': self.joined = False
        elif name == 'SetMute': self.mutes[ip] = str(args['DesiredMute'])
        values = {
            'GetMediaInfo': {'CurrentURI': self.uris[ip], 'CurrentURIMetaData': ''},
            'GetTransportInfo': {'CurrentTransportState': 'PLAYING' if self.playing and ip == B else 'STOPPED', 'CurrentTransportStatus': 'OK'},
            'GetMute': {'CurrentMute': self.mutes[ip]},
            'GetVolume': {'CurrentVolume': '17'},
            'GetZoneGroupState': {'ZoneGroupState': self.topology()},
        }.get(name, {})
        root = E.Element('response')
        for k, v in values.items(): E.SubElement(root, k).text = v
        return {'http_status': 200, 'xml': E.tostring(root).decode()}

class GroupProbeTests(unittest.TestCase):
    def execute(self, household):
        with tempfile.TemporaryDirectory() as directory, patch.object(probe, 'call', household.call), patch.object(probe.socket, 'socket', return_value=FakeSocket()), patch.object(probe, 'NativeSender', FakeSender), contextlib.redirect_stdout(io.StringIO()):
            args = SimpleNamespace(receiver=A, receiver_id=UA, coordinator=B, coordinator_id=UB,
                                   output=str(Path(directory)/'private.json'), seconds=1,
                                   handoff_to_synthetic=False, release_coordinator=False, reset_helper_group=False)
            return probe.run(args)
    def test_playing_helper_refused_before_any_mutation(self):
        household = Household(playing=True)
        with self.assertRaises(RuntimeError): self.execute(household)
        self.assertTrue(all(name.startswith('Get') for _, name, _ in household.calls))
    def test_rejected_setup_restores_both_speakers(self):
        household = Household()
        result = self.execute(household)
        self.assertIn('error', result)
        self.assertEqual(result['restore_errors'], [])
        self.assertTrue(all(all(v.values()) for v in result['verified'].values()))
        self.assertFalse(result['phases'][0]['transport_check_passed'])
    def test_restore_failure_reported_and_other_restores_attempted(self):
        household = Household(fail_restore=True)
        result = self.execute(household)
        self.assertEqual(len(result['restore_errors']), 1)
        self.assertFalse(result['verified'][A]['source'])
        self.assertTrue(all(result['verified'][B].values()))
        for ip in (A, B):
            self.assertTrue(any(i == ip and n == 'SetVolume' for i, n, a in household.calls))
            self.assertTrue(any(i == ip and n == 'SetMute' and str(a['DesiredMute']) == ('0' if ip == A else '1') for i, n, a in household.calls))
    def test_virtual_identity_distinct_local_and_deterministic(self):
        self.assertEqual(probe.virtual_identity(UA), probe.virtual_identity(UA))
        self.assertNotEqual(probe.virtual_identity(UA), probe.virtual_identity(UB))
        self.assertRegex(probe.virtual_identity(UA), r'^RINCON_02[0-9A-F]{10}01400$')

    def completed_phase(self):
        return dict(setup_accepted=True, promotion_accepted=True, duration_seconds=120,
                    stats=dict(packets=21083, clock_requests=135),
                    state=dict(CurrentTransportState='PLAYING', CurrentTransportStatus='OK'),
                    receiver_group_coordinator=UA, receiver_standalone=True, helper_standalone=True)

    def test_paused_receiver_is_not_reported_as_playback_success(self):
        phase = self.completed_phase()
        phase['state']['CurrentTransportState'] = 'PAUSED_PLAYBACK'
        probe.phase_checks(phase, UA, True, 'detach')
        self.assertTrue(phase['sender_check_passed'])
        self.assertFalse(phase['transport_check_passed'])

    def test_detached_promotion_requires_both_standalone(self):
        for key in ('receiver_standalone', 'helper_standalone'):
            with self.subTest(key=key):
                phase = self.completed_phase()
                phase[key] = False
                probe.phase_checks(phase, UA, True, 'detach')
                self.assertFalse(phase['transport_check_passed'])

    def test_full_control_state_required_alongside_sender_progress(self):
        phase = self.completed_phase()
        probe.phase_checks(phase, UA, True, 'detach')
        self.assertTrue(phase['transport_check_passed'])
        phase['stats']['packets'] -= 1
        probe.phase_checks(phase, UA, True, 'detach')
        self.assertFalse(phase['sender_check_passed'])
        self.assertFalse(phase['transport_check_passed'])

if __name__ == '__main__': unittest.main()
