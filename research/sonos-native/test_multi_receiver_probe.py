"""Offline failure-path checks: no network or speaker changes."""
import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as E
import multi_receiver_probe as probe
from test_group_receiver_probe import A, B, UA, UB, FakeSocket, FakeSender, Household

C, UC = '192.0.2.12', 'RINCON_02000000001201400'

class ThreeSpeakers(Household):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.uris[C] = 'original-c'
        self.mutes[C] = '0'
        self.members = set()
    def topology(self):
        root = E.Element('ZoneGroups')
        for ip, uid in ((A,UA),(B,UB),(C,UC)):
            if ip in self.members: continue
            g = E.SubElement(root,'ZoneGroup',Coordinator=uid,ID=uid+':1')
            E.SubElement(g,'ZoneGroupMember',UUID=uid,Location='http://'+ip+':1400/xml/device_description.xml')
            if ip == C:
                for member, member_id in ((A,UA),(B,UB)):
                    if member in self.members: E.SubElement(g,'ZoneGroupMember',UUID=member_id,Location='http://'+member+':1400/xml/device_description.xml')
        return E.tostring(root).decode()
    def call(self, ip, path, service, name, args):
        if name == 'SetAVTransportURI' and args['CurrentURI'].startswith('x-rincon:'): self.members.add(ip)
        if name == 'BecomeCoordinatorOfStandaloneGroup': self.members.discard(ip)
        return super().call(ip,path,service,name,args)

class AllocatedSender(FakeSender):
    next_port = 12000
    closed = 0
    def __init__(self,*args):
        type(self).next_port += 1
        self.clock_port = type(self).next_port
    def close(self): type(self).closed += 1

class MultiReceiverTests(unittest.TestCase):
    def execute(self, household, sender=AllocatedSender):
        with tempfile.TemporaryDirectory() as d, patch.object(probe,'call',household.call), patch.object(probe.socket,'socket',return_value=FakeSocket()), patch.object(probe,'NativeSender',sender), contextlib.redirect_stdout(io.StringIO()):
            return probe.run(SimpleNamespace(first=A,first_id=UA,second=B,second_id=UB,coordinator=C,coordinator_id=UC,seconds=10,first_stop=5,output=str(Path(d)/'private.json')))
    def test_playing_second_receiver_refuses_before_mutation(self):
        h=ThreeSpeakers(playing=True)
        with self.assertRaises(RuntimeError): self.execute(h)
        self.assertTrue(all(n.startswith('Get') for _,n,_ in h.calls))
    def test_rejected_setup_restores_all_three(self):
        r=self.execute(ThreeSpeakers())
        self.assertFalse(r['passed'])
        self.assertIn('error',r)
        self.assertEqual(r['restore_errors'],[])
        self.assertEqual(len(r['verified']),3)
        self.assertTrue(all(all(c.values()) for c in r['verified'].values()))
    def test_failed_source_restore_does_not_skip_other_speakers(self):
        r=self.execute(ThreeSpeakers(fail_restore=True))
        self.assertFalse(r['passed'])
        self.assertEqual(len(r['restore_errors']),1)
        self.assertFalse(r['verified'][A]['source'])
        self.assertTrue(all(r['verified'][B].values()))
        self.assertTrue(all(r['verified'][C].values()))
    def test_second_sender_allocation_failure_closes_first_without_mutation(self):
        h=ThreeSpeakers()
        class FailsSecond(AllocatedSender):
            count=0
            closed=0
            def __init__(self,*args):
                type(self).count += 1
                if self.count == 2: raise OSError('allocation failure')
                super().__init__(*args)
        r=self.execute(h,FailsSecond)
        self.assertFalse(r['passed'])
        self.assertEqual(FailsSecond.closed,1)
        self.assertTrue(all(n.startswith('Get') for _,n,_ in h.calls))

if __name__ == '__main__': unittest.main()
