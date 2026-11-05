"""Run the real frontend backend against a framed IPC child; no network/speakers."""
from pathlib import Path
import json, os, subprocess, tempfile, unittest
ROOT=Path(__file__).resolve().parents[1]
class BackendTest(unittest.TestCase):
    def test_clock_mapping_format_flush_and_close(self):
        with tempfile.TemporaryDirectory() as directory:
            d=Path(directory); worker=d/'worker.py'; capture=d/'frames.json'
            worker.write_text('''#!/usr/bin/env python3
import json,struct,sys,time
from pathlib import Path
frames=[]
def read(n):
    data=b''
    while len(data)<n:
        part=sys.stdin.buffer.read(n-len(data))
        if not part: return None
        data+=part
    return data
print('READY',flush=True)
while True:
    h=read(24)
    if h is None:break
    magic,kind,count,reserved,when=struct.unpack('!IIIIQ',h)
    assert magic==0x41503253 and reserved==0
    data=read(count*4)
    frames.append(dict(type=kind,frames=count,lead_ms=(when-time.clock_gettime_ns(time.CLOCK_MONOTONIC))/1e6,
                       data_ok=not count or data==b'\\x23'*(count*4)))
Path(sys.argv[1]).write_text(json.dumps(frames))
''');worker.chmod(0o700)
            cfg=d/'config';cfg.write_text('airconnect = { worker='+json.dumps(str(worker))+'; helper='+json.dumps(str(capture))+'; local_ip="127.0.0.1"; receiver_url="unused"; receiver_udn="unused"; };')
            subprocess.run([str(ROOT/'tests/bin/test_ap2_backend'),str(cfg)],check=True,timeout=10)
            frames=json.loads(capture.read_text())
            self.assertEqual([x['type'] for x in frames],[1,2,1])
            self.assertEqual([x['frames'] for x in frames],[4096,0,352])
            self.assertTrue(all(x['data_ok'] for x in frames))
            for f in (frames[0],frames[2]):self.assertTrue(0<f['lead_ms']<400,f)
    def test_preparation_failure_exits_instead_of_advertising_silent_success(self):
        with tempfile.TemporaryDirectory() as directory:
            d=Path(directory); worker=d/'failed-worker'
            worker.write_text('#!/bin/sh\nexit 5\n');worker.chmod(0o700)
            cfg=d/'config';cfg.write_text('airconnect = { worker='+json.dumps(str(worker))+'; helper="/unused"; local_ip="127.0.0.1"; receiver_url="unused"; receiver_udn="unused"; };')
            result=subprocess.run([str(ROOT/'tests/bin/test_ap2_backend'),str(cfg)],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,10,result.stderr)
            self.assertIn('preparation failed',result.stderr)
    def test_worker_loss_fails_frontend(self):
        with tempfile.TemporaryDirectory() as directory:
            d=Path(directory); worker=d/'lost-worker'
            worker.write_text('#!/bin/sh\nprintf "READY\\n"\nexit 7\n');worker.chmod(0o700)
            cfg=d/'config';cfg.write_text('airconnect = { worker='+json.dumps(str(worker))+'; helper="/unused"; local_ip="127.0.0.1"; receiver_url="unused"; receiver_udn="unused"; };')
            for mode in ('lost','reaped'):
                result=subprocess.run([str(ROOT/'tests/bin/test_ap2_backend'),str(cfg),mode],capture_output=True,text=True,timeout=5)
                self.assertEqual(result.returncode,10,result.stderr)
                self.assertIn('output failed',result.stderr)
if __name__=='__main__':unittest.main()
