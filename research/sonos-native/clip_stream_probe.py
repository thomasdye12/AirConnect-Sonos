"""Bounded paced-WAV experiment over the local Sonos audioClip API.

Default is silence and mute. This is not a native UDP or AirPlay backend.
Requires a stopped, standalone receiver; verifies its state after the test.
"""
import argparse,json,socket,time,threading,http.server,struct,wave,xml.etree.ElementTree as E
from pathlib import Path
from local_api import LocalAPI
from soap import call
from probe import values,AV,RC
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--receiver',required=True)
parser.add_argument('--receiver-id',required=True)
parser.add_argument('--output',required=True,help='Private JSON log path, including device identifiers')
parser.add_argument('--seconds',type=int,default=12,choices=range(1,61),metavar='1..60')
parser.add_argument('--wav',help='Optional 44.1 kHz, stereo, 16-bit PCM WAV')
parser.add_argument('--streaming',action='store_true',help='Omit HTTP length, use a placeholder WAV length, and explicitly cancel at the time limit')
parser.add_argument('--audible',action='store_true',help='Unmute for the bounded WAV test')
parser.add_argument('--volume',type=int,default=15,choices=range(1,26),metavar='1..25')
args=parser.parse_args()
if args.audible and not args.wav:parser.error('--audible requires --wav')
IP=args.receiver;UID=args.receiver_id;OUT=Path(args.output);duration=args.seconds;rate=44100
OUT.parent.mkdir(parents=True,exist_ok=True)
pcm=None
if args.wav:
 with wave.open(args.wav,'rb') as w:
  if (w.getnchannels(),w.getsampwidth(),w.getframerate(),w.getcomptype())!=(2,2,44100,'NONE'):
   parser.error('WAV must be uncompressed 44.1 kHz stereo 16-bit PCM')
  pcm=w.readframes(duration*rate)
r={'mode':'streaming' if args.streaming else 'finite','actions':[],'events':[],'http':[],'restore_errors':[]};start=time.monotonic();lock=threading.Lock();done=threading.Event()
def now():return round(time.monotonic()-start,4)
def save():
 with lock:OUT.write_text(json.dumps(r,indent=2))
def act(name,args,path=AV,svc='AVTransport'):
 v=call(IP,path,svc,name,args);r['actions'].append({'at':now(),'action':name,'response':v});save();return values(v)
def av(name,**kw):return act(name,{'InstanceID':0,**kw})
def rc(name,**kw):return act(name,{'InstanceID':0,'Channel':'Master',**kw},RC,'RenderingControl')
def group(t):return next((g for g in E.fromstring(t['ZoneGroupState']).iter('ZoneGroup') if any(m.get('UUID')==UID for m in g.iter('ZoneGroupMember'))),None)
def snapshot():return {'media':av('GetMediaInfo'),'transport':av('GetTransportInfo'),'mute':rc('GetMute'),'volume':rc('GetVolume'),'topology':act('GetZoneGroupState',{},'/ZoneGroupTopology/Control','ZoneGroupTopology')}
s=snapshot();r['snapshot']=s;save();g=group(s['topology'])
if g is None or g.get('Coordinator')!=UID or len(list(g.iter('ZoneGroupMember')))!=1:raise SystemExit('Receiver grouped: no mutation')
if s['transport']['CurrentTransportState']!='STOPPED':raise SystemExit('Receiver not stopped: no mutation')
with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as route:route.connect((IP,1400));local=route.getsockname()[0]
size=duration*rate*4
declared_size=0xffffff00 if args.streaming else size
header=struct.pack('<4sI4s4sIHHIIHH4sI',b'RIFF',declared_size+36,b'WAVE',b'fmt ',16,1,2,rate,rate*4,4,16,b'data',declared_size)
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  if self.path!='/probe.wav' or self.client_address[0]!=IP:self.send_error(404);return
  e={'at':now(),'range':self.headers.get('Range'),'bytes_sent':0};r['http'].append(e)
  self.send_response(200);self.send_header('Content-Type','audio/wav')
  if not args.streaming:self.send_header('Content-Length',str(size+44))
  self.send_header('Connection','close');self.end_headers()
  self.connection.settimeout(3)
  try:
   self.wfile.write(header);base=time.monotonic();e['first_byte_at']=now()
   for i in range((duration+15 if args.streaming else duration)*100):
    if done.is_set():break
    delay=base+i*.01-time.monotonic()
    if delay>0:done.wait(delay)
    if done.is_set():break
    chunk=pcm[i*1764:(i+1)*1764].ljust(1764,b'\0') if pcm is not None else bytes(1764)
    self.wfile.write(chunk);e['bytes_sent']+=1764
   e['finished_at']=now()
  except (BrokenPipeError,ConnectionResetError,TimeoutError) as exc:e['error']=str(exc)
  save()
server=http.server.ThreadingHTTPServer((local,0),Handler);server.daemon_threads=True
threading.Thread(target=server.serve_forever,daemon=True).start();api=None;clip=None
try:
 rc('SetMute',DesiredMute=0 if args.audible else 1)
 api=LocalAPI(IP)
 r['subscribe']=api.command('audioClip','subscribe',playerId=UID);save()
 r['load_started_at']=now()
 reply=api.command('audioClip','loadAudioClip',{'name':'Bounded paced audio test','appId':'local.airconnect.native-lab','streamUrl':f'http://{local}:{server.server_port}/probe.wav','volume':args.volume if args.audible else 1,'priority':'LOW'},playerId=UID)
 r['load_response']=reply;r['load_finished_at']=now();clip=reply[1].get('id');r['loaded_clip_id']=clip;save()
 if reply[0].get('success'):
  end=time.monotonic()+duration+(0 if args.streaming else 8)
  while time.monotonic()<end:
   try:
    event=api.receive_event(timeout=min(1,end-time.monotonic()));r['events'].append({'at':now(),'message':event});save()
   except TimeoutError:continue
   statuses=event[1].get('audioClips',[]) if isinstance(event,list) and len(event)==2 and isinstance(event[1],dict) else []
   if clip and any(str(x.get('id'))==str(clip) and x.get('status') in ('DONE','ERROR','DISMISSED') for x in statuses):
    r['terminal_status_observed']=True;clip=None;break
except Exception as exc:r['error']=str(exc)
finally:
 if api:
  if clip:
   try:
    r['cancel_started_at']=now()
    r['cancel_response']=api.command('audioClip','cancelAudioClip',{'id':clip},playerId=UID)
    r['cancel_finished_at']=now()
    if not r['cancel_response'][0].get('success') and r['cancel_response'][1].get('errorCode')!='ERROR_AUDIO_CLIP_ID_NOT_FOUND':
     r['restore_errors'].append({'step':'cancel','error':'Receiver rejected cancellation; see cancel_response'})
    deadline=time.monotonic()+1
    while time.monotonic()<deadline:
     try:r['events'].append({'at':now(),'message':api.receive_event(timeout=max(.01,deadline-time.monotonic()))})
     except TimeoutError:break
   except Exception as exc:r['restore_errors'].append({'step':'cancel','error':str(exc)})
  api.close()
 done.set();server.shutdown();server.server_close()
 try:rc('SetMute',DesiredMute=s['mute']['CurrentMute'])
 except Exception as exc:r['restore_errors'].append({'step':'mute','error':str(exc)})
 try:
  f=snapshot();r['restored']=f;fg=group(f['topology'])
  r['verified']={k:f[k]==s[k] for k in ['transport','mute','volume']}
  r['verified']['source']=all(f['media'].get(k)==s['media'].get(k) for k in ['CurrentURI','CurrentURIMetaData'])
  r['verified']['standalone']=fg is not None and fg.get('Coordinator')==UID and len(list(fg.iter('ZoneGroupMember')))==1
 except Exception as exc:r['restore_errors'].append({'step':'verify','error':str(exc)})
 save()
summary={k:r[k] for k in ['error','http','verified','restore_errors','terminal_status_observed'] if k in r}
summary['states']=[{'at':e['at'],'states':[x.get('status') for x in e['message'][1].get('audioClips',[]) if x.get('id')==r.get('loaded_clip_id')]} for e in r['events']]
summary['states']=[x for x in summary['states'] if x['states']]
states=[s for e in summary['states'] for s in e['states']]
summary['paced_stream_test_passed']=('ACTIVE' in states and ('DISMISSED' if args.streaming else 'DONE') in states and not r.get('error') and not r['restore_errors'] and all(r.get('verified',{}).values()))
summary['audible']=args.audible
summary['latency_measured']=False
r['summary']=summary;save()
print(json.dumps(summary,indent=2))
if not summary['paced_stream_test_passed']:raise SystemExit(1)
