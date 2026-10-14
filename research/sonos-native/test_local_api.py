"""Transport-level tests for event delivery under real socket read boundaries."""
from collections import deque
import json,struct,time,unittest
from local_api import LocalAPI

class ScriptedSocket:
    def __init__(self,chunks):self.chunks=deque(chunks);self.sent=[]
    def recv(self,n):
        item=self.chunks.popleft()
        if isinstance(item,Exception):raise item
        if len(item)>n:self.chunks.appendleft(item[n:]);item=item[:n]
        return item
    def sendall(self,data):self.sent.append(data)
    def settimeout(self,value):pass

def frame(payload,opcode=1,final=True):
    n=len(payload)
    return bytes([(128 if final else 0)|opcode,n if n<126 else 126])+(struct.pack('!H',n) if n>=126 else b'')+payload

def client(chunks):
    c=LocalAPI.__new__(LocalAPI)
    c.socket=ScriptedSocket(chunks);c.pending=bytearray();c.events=deque(maxlen=256)
    c.fragment=bytearray();c.fragment_started=False;c.timeout=1;c.counter=0;c.household_id=None
    c.deadline=time.monotonic()+1
    return c

class LocalAPITests(unittest.TestCase):
    def test_events_before_command_reply_are_preserved(self):
        event=[{'name':'audioClipStatus'},{'audioClips':[{'status':'ACTIVE'}]}]
        reply=[{'cmdId':'native-lab-1','success':True},{}]
        c=client([frame(json.dumps(event).encode())+frame(json.dumps(reply).encode())])
        self.assertEqual(c.command('audioClip','subscribe'),reply)
        self.assertEqual(c.receive_event(),event)
        self.assertEqual(len(c.socket.sent),1)

    def test_timeout_at_each_byte_boundary_can_resume(self):
        expected=[{'name':'audioClipStatus'},{'padding':'x'*140}]
        wire=frame(json.dumps(expected).encode())
        for split in range(1,len(wire)):
            with self.subTest(split=split):
                c=client([wire[:split],TimeoutError(),wire[split:]])
                with self.assertRaises(TimeoutError):c.receive_event()
                self.assertEqual(c.receive_event(),expected)

    def test_fragmented_message_survives_poll_timeout_and_ping(self):
        expected=[{'name':'audioClipStatus'},{'audioClips':[]}]
        raw=json.dumps(expected).encode();cut=17
        c=client([frame(raw[:cut],final=False),TimeoutError(),frame(b'ping',opcode=9)+frame(raw[cut:],opcode=0)])
        with self.assertRaises(TimeoutError):c.receive_event()
        self.assertEqual(c.receive_event(),expected)
        pong=c.socket.sent[0];self.assertEqual(pong[0],0x8a)
        self.assertTrue(pong[1]&128)
        mask=pong[2:6]
        self.assertEqual(bytes(b^mask[i%4] for i,b in enumerate(pong[6:])),b'ping')

    def test_oversized_frame_rejected_before_payload_read(self):
        c=client([b'\x81\x7f'+struct.pack('!Q',4*1024*1024+1)])
        with self.assertRaisesRegex(ValueError,'Oversized frame'):c.receive_event()

if __name__=='__main__':unittest.main()
