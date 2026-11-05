#!/usr/bin/env python3
"""Drive the AP2 worker through the existing local fake-Sonos lifecycle harness."""
import os, re, selectors, struct, subprocess, sys, time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
helper,local,url,uuid,seconds,volume=sys.argv[1:]
child=subprocess.Popen([str(root/'bin/airconnect-ap2-worker'),helper,local,url,uuid,volume,'1'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
# Drain diagnostic pipe concurrently, so a verbose failure cannot deadlock cleanup.
import threading
logs=[]
thread=threading.Thread(target=lambda: logs.append(child.stderr.read()));thread.start()
sel=selectors.DefaultSelector();sel.register(child.stdout,selectors.EVENT_READ)
ready=False;limit=time.monotonic()+18
try:
    while time.monotonic()<limit:
        if sel.select(.2):
            line=child.stdout.readline()
            if not line:break
            if line==b'READY\n':ready=True;break
    if ready:
        begin=time.monotonic();epoch=time.clock_gettime_ns(time.CLOCK_MONOTONIC)+200000000
        frames=0;flushed=False
        for packet in range(200):
            if not flushed and frames>=44100:
                child.stdin.write(struct.pack('!IIIIQ',0x41503253,2,0,0,0));flushed=True
            child.stdin.write(struct.pack('!IIIIQ',0x41503253,1,441,0,epoch+frames*1000000000//44100)+b'\x23\x01\x23\x01'*441)
            child.stdin.flush();frames+=441;time.sleep(max(0,begin+(packet+1)*.01-time.monotonic()))
except BrokenPipeError:pass
finally:
    child.stdin.close()
try:rc=child.wait(timeout=35)
except subprocess.TimeoutExpired:
    child.kill();child.wait();raise
thread.join();log=b''.join(logs).decode();sys.stderr.write(log)
if rc==0:
    assert ready and 'received=88200' in log,log
sys.exit(0 if rc==0 else 5 if rc in (3,4,5) else 6)
