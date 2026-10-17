"""Compare the C codec against every audio packet in a supplied capture."""
import ctypes as C,pathlib,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from linein import read_udp,AudioPacket
lib=C.CDLL(sys.argv[1]);p=C.POINTER(C.c_ubyte)
lib.sonos_packet_encode.argtypes=[p,C.c_size_t,C.c_uint32,C.c_uint64,C.c_uint32,p,C.c_size_t]
lib.sonos_packet_encode.restype=C.c_size_t
lib.sonos_packet_decode.argtypes=[p,C.c_size_t,C.POINTER(C.c_uint32),C.POINTER(C.c_uint64),C.POINTER(C.c_uint32),p,C.c_size_t]
lib.sonos_packet_decode.restype=C.c_int
count=0
for d in read_udp(sys.argv[2]):
 if d.destination_port!=7020 or len(d.data)<28:continue
 q=AudioPacket.decode(d.data);buf=(C.c_ubyte*len(d.data)).from_buffer_copy(d.data)
 seq=C.c_uint32();us=C.c_uint64();pos=C.c_uint32();pcm=(C.c_ubyte*1004)();out=(C.c_ubyte*1032)()
 assert lib.sonos_packet_decode(buf,len(d.data),C.byref(seq),C.byref(us),C.byref(pos),pcm,1004)==1
 assert (seq.value,us.value,pos.value,bytes(pcm))==(q.sequence,q.seconds*1000000+q.microseconds,q.byte_position,q.pcm)
 n=lib.sonos_packet_encode(out,1032,seq.value,us.value,pos.value,pcm,1004)
 assert bytes(out[:n])==d.data
 count+=1
assert count>0
print('C decoder and encoder matched all',count,'captured audio packets exactly')
