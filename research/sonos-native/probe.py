#!/usr/bin/env python3
"""Bounded, muted native transport probe. Restores source, state and mute in finally.
Requires a known real line-in source. Does NOT emulate Sonos discovery/identity.
"""
import argparse,json,pathlib,socket,struct,threading,time,math,wave,xml.etree.ElementTree as E
from linein import AudioPacket
from soap import call
from transport import clock_timestamp

AV='/MediaRenderer/AVTransport/Control'; RC='/MediaRenderer/RenderingControl/Control'
def values(r):
    if r['http_status']!=200: raise RuntimeError(r)
    return {e.tag.split('}')[-1]:e.text or '' for e in E.fromstring(r['xml']).iter() if not len(e)}
def main(a):
    wav_pcm=None
    if getattr(a,'wav',None):
        with wave.open(a.wav,'rb') as w:
            if (w.getnchannels(),w.getsampwidth(),w.getframerate(),w.getcomptype())!=(2,2,44100,'NONE'):
                raise ValueError('WAV must be uncompressed 44.1 kHz stereo 16-bit PCM')
            wav_pcm=w.readframes(min(w.getnframes(),int(a.seconds*44100)))
    log=[];result={};done=threading.Event();stats={'clock_requests':0,'audio_packets_sent':0,'other_requests':[]}
    def act(ip,path,service,name,args):
        r=call(ip,path,service,name,args);log.append({'action':name,'response':r});return values(r)
    if getattr(a,'group_member',False):
        topology=act(a.receiver,'/ZoneGroupTopology/Control','ZoneGroupTopology','GetZoneGroupState',{})
        groups=E.fromstring(topology['ZoneGroupState'])
        for device in ((a.receiver_id,) if getattr(a,'synthetic_coordinator',False) else (a.receiver_id,a.source_id)):
            group=next((g for g in groups.iter('ZoneGroup') if any(m.get('UUID')==device for m in g.iter('ZoneGroupMember'))),None)
            if group is None or group.get('Coordinator')!=device or len(list(group.iter('ZoneGroupMember')))!=1:
                raise RuntimeError('Both test devices must be standalone before group-member probe')
    media=act(a.receiver,AV,'AVTransport','GetMediaInfo',{'InstanceID':0})
    state=act(a.receiver,AV,'AVTransport','GetTransportInfo',{'InstanceID':0})
    mute=act(a.receiver,RC,'RenderingControl','GetMute',{'InstanceID':0,'Channel':'Master'})
    if not getattr(a,'allow_other_source',False) and not media['CurrentURI'].startswith('x-rincon-stream:'+a.source_id):
        raise RuntimeError('Receiver is not on the specified line-in source; refusing to replace unrelated playback')
    if state['CurrentTransportState'] not in ('PLAYING','PAUSED_PLAYBACK','STOPPED'):
        raise RuntimeError('Unexpected receiver state')
    volume=act(a.receiver,RC,'RenderingControl','GetVolume',{'InstanceID':0,'Channel':'Master'})
    result['snapshot']={'media':media,'state':state,'mute':mute,'volume':volume}
    out=pathlib.Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2))
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);sock.connect((a.receiver,7020));local=sock.getsockname()[0]
    native=None;clock=None;thread=None
    if getattr(a,'native_library',None):
        from native_sender import NativeSender
        native=NativeSender(a.native_library,local,a.receiver)
    else:
        clock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);clock.bind((local,12300));clock.settimeout(.1)
    # Use the same standard NTP conversion as the native sender.
    def timestamp():
        return clock_timestamp(time.monotonic())
    def clock_server():
        while not done.is_set():
            try:data,addr=clock.recvfrom(2048)
            except socket.timeout:continue
            if addr[0]!=a.receiver or len(data)!=48:continue
            response=bytearray(48);response[:4]=bytes.fromhex('1c0f0800');response[24:32]=data[40:48]
            response[32:40]=timestamp();response[40:48]=timestamp();clock.sendto(response,addr)
            stats['clock_requests']+=1
    if not native:
        thread=threading.Thread(target=clock_server,daemon=True);thread.start()
    changed=False
    try:
        changed=True
        act(a.receiver,RC,'RenderingControl','SetMute',{'InstanceID':0,'Channel':'Master','DesiredMute':1})
        if getattr(a,'synthetic_coordinator',False):
            # Experimental: no control calls or transport settings from a real source.
            original='234.142.199.198:7020,'+local+':7000:7010:12300,'+a.source_id
        else:
            original=act(a.source,'/AudioIn/Control','AudioIn','StartTransmissionToGroup',{'ObjectID':'0','CoordinatorID':a.receiver_id})['CurrentTransportSettings']
        result['original_transport_settings']=original
        probe_uri=media['CurrentURI']
        if getattr(a,'group_member',False):
            probe_uri='x-rincon:'+a.source_id
            if getattr(a,'direct_change',False):
                act(a.receiver,AV,'AVTransport','ChangeCoordinator',{'InstanceID':0,'CurrentCoordinator':a.receiver_id,'NewCoordinator':a.source_id,'NewTransportSettings':original,'CurrentAVTransportURI':probe_uri,'RestartSink':1})
            else:
                act(a.receiver,AV,'AVTransport','SetAVTransportURI',{'InstanceID':0,'CurrentURI':probe_uri,'CurrentURIMetaData':''})
            time.sleep(1)
        elif state['CurrentTransportState']!='PLAYING':act(a.receiver,AV,'AVTransport','Play',{'InstanceID':0,'Speed':'1'})
        clock_port=native.clock_port if native else 12300
        settings=original.split(',');settings[1]=local+':7000:7010:'+str(clock_port)
        result['probe_transport_settings']=','.join(settings)
        act(a.receiver,AV,'AVTransport','ChangeTransportSettings',{'InstanceID':0,'NewTransportSettings':','.join(settings),'CurrentAVTransportURI':probe_uri})
        if getattr(a,'tone',False) or wav_pcm is not None:
            act(a.receiver,RC,'RenderingControl','SetVolume',{'InstanceID':0,'Channel':'Master','DesiredVolume':a.tone_volume})
            act(a.receiver,RC,'RenderingControl','SetMute',{'InstanceID':0,'Channel':'Master','DesiredMute':0})
        base=time.monotonic();count=int(a.seconds*44100/251)
        # Silence, untrimmed packets: optional zero-tail compression is not required
        # for the first probe; avoids confusing an all-zero PCM block with control.
        for i in range(count):
            deadline=base+i*251/44100
            delay=deadline-time.monotonic()
            if delay>0 and not native:time.sleep(delay)
            ts=deadline+.075;sec=int(ts)
            pcm=bytes(1004)
            if getattr(a,'tone',False):
                samples=[]
                for j in range(251):
                    t=(i*251+j)/44100
                    envelope=min(1,t/.2,max(0,(a.seconds-t)/.2))
                    value=int(6000*envelope*math.sin(2*math.pi*440*t))
                    samples.append(struct.pack('<hh',value,value))
                pcm=b''.join(samples)
            if wav_pcm is not None:
                pcm=wav_pcm[i*1004:(i+1)*1004].ljust(1004,b'\0')
            if native:native.write(pcm)
            else:
                packet=AudioPacket(i%65536,sec,int((ts-sec)*1e6),i*1004,pcm).encode()
                sock.send(packet)
            stats['audio_packets_sent']+=1
        result['after']=act(a.receiver,AV,'AVTransport','GetTransportInfo',{'InstanceID':0})
    except Exception as e:result['error']=str(e)
    finally:
        if changed:
            result['restore_errors']=[]
            try:act(a.receiver,RC,'RenderingControl','SetMute',{'InstanceID':0,'Channel':'Master','DesiredMute':1})
            except Exception as e:result['restore_errors'].append(str(e))
            try:
                if getattr(a,'group_member',False):
                    act(a.receiver,AV,'AVTransport','BecomeCoordinatorOfStandaloneGroup',{'InstanceID':0})
                # SetAVTransportURI re-establishes the real source. Do not repeat
                # a rejected ChangeTransportSettings action during restoration.
                act(a.receiver,AV,'AVTransport','SetAVTransportURI',{'InstanceID':0,'CurrentURI':media['CurrentURI'],'CurrentURIMetaData':media['CurrentURIMetaData']})
                if state['CurrentTransportState'] in ('PLAYING','PAUSED_PLAYBACK'):
                    act(a.receiver,AV,'AVTransport','Play',{'InstanceID':0,'Speed':'1'})
                    if state['CurrentTransportState']=='PAUSED_PLAYBACK':
                        time.sleep(1)
                        act(a.receiver,AV,'AVTransport','Pause',{'InstanceID':0})
                else:act(a.receiver,AV,'AVTransport','Stop',{'InstanceID':0})
            except Exception as e:result['restore_errors'].append(str(e))
            try:act(a.receiver,RC,'RenderingControl','SetVolume',{'InstanceID':0,'Channel':'Master','DesiredVolume':volume['CurrentVolume']})
            except Exception as e:result['restore_errors'].append(str(e))
            try:act(a.receiver,RC,'RenderingControl','SetMute',{'InstanceID':0,'Channel':'Master','DesiredMute':mute['CurrentMute']})
            except Exception as e:result['restore_errors'].append(str(e))
        done.set()
        if native:
            result['native_stats']=native.stats()
            stats['clock_requests']=result['native_stats']['clock_requests']
            native.close()
        else:
            thread.join(1);clock.close()
        sock.close()
        result['stats']=stats;result['actions']=log
        out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('actions','snapshot')},indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for x in ['receiver','receiver-id','source','source-id','output']:p.add_argument('--'+x,required=True)
    p.add_argument('--native-library',help='Use the compiled C audio sender and clock service')
    p.add_argument('--allow-other-source',action='store_true',help='Explicitly allow taking over another source and attempting to restore it')
    p.add_argument('--wav',help='Play a 44.1 kHz / stereo / 16-bit PCM WAV instead of silence')
    p.add_argument('--tone',action='store_true',help='Play a quiet 440 Hz tone, restoring original volume afterward')
    p.add_argument('--tone-volume',type=int,default=15)
    p.add_argument('--group-member',action='store_true')
    p.add_argument('--synthetic-coordinator',action='store_true',help='Experimental: use generated settings and a synthetic source ID, without contacting a real source')
    p.add_argument('--direct-change',action='store_true',help='Experimental: try ChangeCoordinator directly from the standalone receiver')
    p.add_argument('--seconds',type=float,default=10);a=p.parse_args()
    if a.tone and a.wav:p.error('Choose tone or WAV, not both')
    if a.direct_change and not a.synthetic_coordinator:p.error('Direct change is only for the synthetic coordinator probe')
    if a.synthetic_coordinator and (not a.group_member or a.source_id!='RINCON_020000AC000101400'):
        p.error('Synthetic probe requires --group-member and the dedicated experimental source ID')
    if not 0<=a.tone_volume<=25:p.error('Test tone volume must be 0..25')
    if not 1<=a.seconds<=20:p.error('Probe duration must be 1..20 seconds')
    main(a)
