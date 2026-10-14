import math,socket,struct,threading,time,unittest
from linein import AudioPacket
from transport import clock_timestamp,clock_response,packetize,send_pcm

class CodecTests(unittest.TestCase):
    def test_zero_tail_variants(self):
        for zeros in (0,1,2,3,1004):
            pcm=b'\x01'*(1004-zeros)+bytes(zeros)
            p=AudioPacket(65535,1900000,123456,0,pcm)
            raw=p.encode();q=AudioPacket.decode(raw)
            self.assertEqual(q.pcm,pcm)
            self.assertEqual(q.omitted_zeros,zeros)
            self.assertEqual(raw,q.encode())
    def test_truncated_header(self):
        with self.assertRaises(ValueError):AudioPacket.decode(bytes(27))
    def test_unknown_format(self):
        raw=bytearray(AudioPacket(0,1,0,0,bytes(1004)).encode());raw[24]=1
        with self.assertRaises(ValueError):AudioPacket.decode(raw)
    def test_sequence_wrap_and_timing(self):
        ps=[AudioPacket.decode(p) for p in packetize(bytes(1004*3),100.25,65534)]
        self.assertEqual([p.sequence for p in ps],[65534,65535,0])
        self.assertEqual([p.byte_position for p in ps],[0,1004,2008])
        self.assertAlmostEqual(ps[2].microseconds-ps[0].microseconds,2*251/44100*1e6,delta=1)
    def test_partial_pcm_rejected(self):
        with self.assertRaises(ValueError):list(packetize(bytes(4),0))
    def test_clock_matches_observed_representation(self):
        # Values from one observed reply, represented without device identifiers.
        self.assertEqual(clock_timestamp(1896563.975895),bytes.fromhex('83c76ef3ee417000'))
    def test_clock_origin_echo(self):
        request=bytearray(48);request[0]=0x1b;request[40:48]=b'12345678'
        response=clock_response(request,100.25,100.5)
        self.assertEqual(response[24:32],b'12345678')
        self.assertEqual(response[32:40],clock_timestamp(100.25))
        self.assertEqual(response[40:48],clock_timestamp(100.5))
    def test_bad_clock_request(self):
        with self.assertRaises(ValueError):clock_response(bytes(48),0,0)
    def test_loopback_sender(self):
        # Real UDP loopback; checks timing, sequence, PCM content and no missing packets.
        pcm=b''.join(struct.pack('<hh',int(1000*math.sin(i*.1)),int(500*math.sin(i*.2))) for i in range(251*20))
        received=[]
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as rx, socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as tx:
            rx.bind(('127.0.0.1',0));rx.settimeout(2);tx.connect(rx.getsockname())
            def reader():
                for _ in range(20):received.append((time.monotonic(),rx.recv(2048)))
            t=threading.Thread(target=reader);t.start();send_pcm(tx,pcm);t.join(3)
        self.assertEqual(len(received),20)
        decoded=[AudioPacket.decode(d) for _,d in received]
        self.assertEqual(b''.join(p.pcm for p in decoded),pcm)
        self.assertEqual([p.sequence for p in decoded],list(range(20)))
        self.assertAlmostEqual(received[-1][0]-received[0][0],19*251/44100,delta=.05)

if __name__=='__main__':unittest.main()
