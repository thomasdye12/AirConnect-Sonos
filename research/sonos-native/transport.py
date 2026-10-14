"""Experimental clock and packet generation helpers. No device identity emulation."""
import struct
import time
from linein import AudioPacket

NTP_EPOCH = 2208988800

def clock_timestamp(seconds):
    micros = round(seconds*1e6)
    whole, fraction = divmod(micros, 1000000)
    return struct.pack('!II', (whole+NTP_EPOCH)&0xffffffff, fraction<<12)

def clock_response(request, received, sent):
    if len(request) != 48 or request[0]&7 != 3:
        raise ValueError('Expected a 48-byte NTP client request')
    response = bytearray(48)
    response[:4] = bytes.fromhex('1c0f0800')
    response[24:32] = request[40:48]
    response[32:40] = clock_timestamp(received)
    response[40:48] = clock_timestamp(sent)
    return bytes(response)

def packetize(pcm, start_time, sequence=0, byte_position=0):
    if len(pcm)%1004:
        raise ValueError('PCM input must contain whole 251-frame packets')
    for n,offset in enumerate(range(0,len(pcm),1004)):
        ts=start_time+n*251/44100
        sec=int(ts)
        yield AudioPacket((sequence+n)&65535,sec,int((ts-sec)*1e6),
                          (byte_position+offset)&0xffffffff,pcm[offset:offset+1004]).encode()

def send_pcm(sock, pcm, lead_seconds=.1):
    start=time.monotonic()
    for n,data in enumerate(packetize(pcm,start+lead_seconds)):
        delay=start+n*251/44100-time.monotonic()
        if delay>0:time.sleep(delay)
        sock.send(data)
