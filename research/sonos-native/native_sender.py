"""ctypes harness for testing the portable C sender, not a production dependency."""
import ctypes as C,os
class Stats(C.Structure):
    _fields_=[('packets',C.c_uint64),('clock_requests',C.c_uint64),('late_packets',C.c_uint64)]
class NativeSender:
    def __init__(self,library,local,peer,*,audio_port=7020,clock_port=0):
        if not 1 <= audio_port <= 65535 or not 0 <= clock_port <= 65535:
            raise ValueError('Invalid audio or clock port')
        self.lib=C.CDLL(library,use_errno=True)
        self.lib.sonos_sender_open.argtypes=[C.c_char_p,C.c_char_p,C.c_uint16,C.c_uint16,C.c_uint32]
        self.lib.sonos_sender_open.restype=C.c_void_p
        self.lib.sonos_sender_clock_port.argtypes=[C.c_void_p]
        self.lib.sonos_sender_clock_port.restype=C.c_uint16
        self.lib.sonos_sender_write.argtypes=[C.c_void_p,C.c_void_p,C.c_size_t]
        self.lib.sonos_sender_write.restype=C.c_int
        self.lib.sonos_sender_get_stats.argtypes=[C.c_void_p,C.POINTER(Stats)]
        self.lib.sonos_sender_close.argtypes=[C.c_void_p]
        self.ctx=self.lib.sonos_sender_open(local.encode(),peer.encode(),audio_port,clock_port,75000)
        if not self.ctx:raise OSError(C.get_errno(),os.strerror(C.get_errno()))
        self.clock_port=self.lib.sonos_sender_clock_port(self.ctx)
    def write(self,pcm):
        if not self.ctx:raise RuntimeError('Sender is closed')
        buf=C.create_string_buffer(pcm)
        if self.lib.sonos_sender_write(self.ctx,buf,len(pcm)):
            raise OSError(C.get_errno(),os.strerror(C.get_errno()))
    def stats(self):
        if not self.ctx:raise RuntimeError('Sender is closed')
        s=Stats();self.lib.sonos_sender_get_stats(self.ctx,C.byref(s));return {name:getattr(s,name) for name,_ in Stats._fields_}
    def close(self):
        if self.ctx:self.lib.sonos_sender_close(self.ctx);self.ctx=None
