#!/usr/bin/env python3
"""Temporary virtual line-in discovery experiment. No audio is sent.
Advertises one synthetic device, briefly selects it on a muted test receiver,
and restores the original source/state/mute before withdrawing the advertisement.
"""
import argparse,http.server,json,pathlib,socket,ssl,threading,time,urllib.request,uuid,xml.etree.ElementTree as E
from soap import call
from probe import values,AV,RC

DEVICE='urn:schemas-upnp-org:device:ZonePlayer:1'
FAKE='RINCON_020000AC000101400'
D='urn:schemas-upnp-org:device-1-0'

def run(a):
    events=[];log=[];stop=threading.Event();restore=[]
    def act(action,args,path=AV,service='AVTransport'):
        r=call(a.receiver,path,service,action,args);log.append({'action':action,'response':r});return values(r)
    media=act('GetMediaInfo',{'InstanceID':0});state=act('GetTransportInfo',{'InstanceID':0})
    mute=act('GetMute',{'InstanceID':0,'Channel':'Master'},RC,'RenderingControl')
    if not a.allow_other_source and not media['CurrentURI'].startswith('x-rincon-stream:'):raise RuntimeError('Test receiver must already be on line-in')
    topology=act('GetZoneGroupState',{},'/ZoneGroupTopology/Control','ZoneGroupTopology')
    groups=E.fromstring(topology['ZoneGroupState'])
    target=next((g for g in groups.iter('ZoneGroup') if any(a.receiver in m.get('Location','').split('/')[2].split(':')[0:1] for m in g.iter('ZoneGroupMember'))),None)
    if target is None or len(list(target.iter('ZoneGroupMember')))!=1:raise RuntimeError('Test receiver must be standalone')
    if state['CurrentTransportState'] not in ('PLAYING','PAUSED_PLAYBACK','STOPPED'):raise RuntimeError('Unexpected playback state')
    out=pathlib.Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    snapshot={'media':media,'state':state,'mute':mute};out.write_text(json.dumps({'snapshot':snapshot},indent=2))
    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect((a.receiver,1400));local=s.getsockname()[0];s.close()
    desc=urllib.request.urlopen('http://'+a.source+':1400/xml/device_description.xml',timeout=5).read()
    root=E.fromstring(desc)
    for elem in root.iter():
        tag=elem.tag.split('}')[-1]
        if tag=='UDN':
            suffix='_MS' if (elem.text or '').endswith('_MS') else '_MR' if (elem.text or '').endswith('_MR') else ''
            elem.text='uuid:'+FAKE+suffix
        elif tag=='serialNum':elem.text='02-00-00-AC-00-01:A'
        elif tag=='roomName':elem.text='Experimental Line-In'
        elif tag=='friendlyName':elem.text='Experimental Line-In ('+local+')'
        elif tag=='MACAddress':elem.text='02:00:00:AC:00:01'
    # No real device certificate or identity is copied.
    for parent in root.iter():
        for child in list(parent):
            tag=child.tag.split('}')[-1]
            if tag=='X_Rhapsody-Extension' or (not a.tls_cert and tag in ('SSLPort','HHSSLPort','securehhSSLPort')):parent.remove(child)
    # Preserve the unprefixed device schema used by real device descriptions.
    E.register_namespace('',D)
    descriptor=E.tostring(root,encoding='utf-8',xml_declaration=True)
    settings='234.142.199.198:7020,'+local+':7000:7010:12300,'+FAKE
    zone='<ZoneGroupState><ZoneGroups><ZoneGroup Coordinator="'+FAKE+'" ID="'+FAKE+':1"><ZoneGroupMember UUID="'+FAKE+'" Location="http://'+local+':1400/xml/device_description.xml" ZoneName="Experimental Line-In" Configuration="1" SoftwareVersion="86.10-80260" SWGen="2" BootSeq="1"/></ZoneGroup></ZoneGroups></ZoneGroupState>'
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,body=b'',code=200,headers=None):
            self.send_response(code);self.send_header('Content-Length',str(len(body)));self.send_header('Content-Type','text/xml')
            for k,v in (headers or {}).items():self.send_header(k,v)
            self.end_headers();self.wfile.write(body)
        def do_GET(self):
            events.append({'method':'GET','path':self.path,'peer':self.client_address[0]})
            if self.path=='/xml/device_description.xml':self.reply(descriptor)
            elif self.path.startswith('/xml/') and self.path.endswith('.xml'):
                try:self.reply(urllib.request.urlopen('http://'+a.source+':1400'+self.path,timeout=3).read())
                except Exception:self.reply(code=404)
            else:self.reply(code=404)
        def do_SUBSCRIBE(self):
            events.append({'method':'SUBSCRIBE','path':self.path,'peer':self.client_address[0]})
            self.reply(headers={'SID':'uuid:'+str(uuid.uuid4()),'TIMEOUT':'Second-60'})
        def do_UNSUBSCRIBE(self):self.reply()
        def do_POST(self):
            n=int(self.headers.get('Content-Length','0'))
            if n>65536:self.reply(code=413);return
            body=self.rfile.read(n)
            action=self.headers.get('SOAPACTION','').strip('"');service,_,name=action.partition('#')
            events.append({'method':'POST','action':name,'peer':self.client_address[0]})
            mapping={'StartTransmissionToGroup':{'CurrentTransportSettings':settings},'StopTransmissionToGroup':{},
                     'GetZoneGroupState':{'ZoneGroupState':zone},'GetAudioInputAttributes':{'CurrentName':'Experimental Line-In','CurrentIcon':'AudioComponent'},
                     'GetHouseholdID':{'CurrentHouseholdID':a.household},'GetZoneAttributes':{'CurrentZoneName':'Experimental Line-In','CurrentIcon':'','CurrentConfiguration':'1'},
                     'GetZoneInfo':{'SerialNumber':'02-00-00-AC-00-01:A','SoftwareVersion':'86.10-80260','DisplaySoftwareVersion':'16.0','HardwareVersion':'1.0','IPAddress':local,'MACAddress':'02:00:00:AC:00:01','CopyrightInfo':'Experimental source','ExtraInfo':'','HTAudioIn':0,'Flags':0}}
            if name not in mapping:self.reply(code=500);return
            env=E.Element('{http://schemas.xmlsoap.org/soap/envelope/}Envelope');b=E.SubElement(env,'{http://schemas.xmlsoap.org/soap/envelope/}Body');r=E.SubElement(b,'{'+service+'}'+name+'Response')
            for k,v in mapping[name].items():E.SubElement(r,k).text=str(v)
            self.reply(E.tostring(env))
    server=http.server.ThreadingHTTPServer((local,1400),Handler);server.daemon_threads=True
    threading.Thread(target=server.serve_forever,daemon=True).start()
    tls_servers=[]
    if a.tls_cert:
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(a.tls_cert,a.tls_key)
        class TLSServer(http.server.ThreadingHTTPServer):
            daemon_threads=True
            def get_request(self):
                conn,peer=super().get_request();conn.settimeout(3)
                try:
                    wrapped=context.wrap_socket(conn,server_side=True)
                    events.append({'method':'TLS','peer':peer[0],'port':self.server_port,'result':'handshake accepted'})
                    return wrapped,peer
                except Exception as exc:
                    events.append({'method':'TLS','peer':peer[0],'port':self.server_port,'error':str(exc)})
                    conn.close();raise
        for port in (1443,1843):
            srv=TLSServer((local,port),Handler);tls_servers.append(srv)
            threading.Thread(target=srv.serve_forever,daemon=True).start()
    udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM,socket.IPPROTO_UDP)
    udp.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);udp.bind(('',1900))
    udp.setsockopt(socket.IPPROTO_IP,socket.IP_ADD_MEMBERSHIP,socket.inet_aton('239.255.255.250')+socket.inet_aton(local));udp.settimeout(.2)
    udp.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_IF,socket.inet_aton(local));udp.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_TTL,2)
    location='http://'+local+':1400/xml/device_description.xml'
    types=[DEVICE,'upnp:rootdevice','uuid:'+FAKE]
    def packet(target,notify=False,bye=False):
        usn='uuid:'+FAKE+('::'+target if target!='uuid:'+FAKE else '')
        h=['NOTIFY * HTTP/1.1' if notify else 'HTTP/1.1 200 OK']
        if notify:h+=['HOST: 239.255.255.250:1900','NT: '+target,'NTS: '+('ssdp:byebye' if bye else 'ssdp:alive')]
        else:h+=['ST: '+target,'EXT:']
        h+=['USN: '+usn,'LOCATION: '+location,'CACHE-CONTROL: max-age=30','SERVER: Linux UPnP/1.0 Sonos/86.10-80260 (ZP90)','X-RINCON-HOUSEHOLD: '+a.household,'X-RINCON-BOOTSEQ: 1']
        return ('\r\n'.join(h)+'\r\n\r\n').encode()
    def listen():
        while not stop.is_set():
            try:data,peer=udp.recvfrom(8192)
            except socket.timeout:continue
            if not data.startswith(b'M-SEARCH'):continue
            for target in types:
                if target.encode() in data or b'ssdp:all' in data:udp.sendto(packet(target),peer)
    threading.Thread(target=listen,daemon=True).start()
    error=None
    try:
        for _ in range(3):
            for target in types:
                udp.sendto(packet(target,True),('239.255.255.250',1900))
                udp.sendto(packet(target,True),(a.receiver,1900))
            time.sleep(3)
        observed=act('GetZoneGroupState',{},'/ZoneGroupTopology/Control','ZoneGroupTopology')
        topology_root=E.fromstring(observed.get('ZoneGroupState','<empty/>'))
        devices=[dict(e.attrib) for e in topology_root.iter() if e.get('UUID')==FAKE]
        events.append({'checkpoint':'before-selection','synthetic_devices':devices})
        act('SetMute',{'InstanceID':0,'Channel':'Master','DesiredMute':1},RC,'RenderingControl')
        uri='x-rincon:'+FAKE if a.group_member else 'x-rincon-stream:'+FAKE+':0'
        act('SetAVTransportURI',{'InstanceID':0,'CurrentURI':uri,'CurrentURIMetaData':''})
        if a.group_member:
            time.sleep(1)
            act('ChangeTransportSettings',{'InstanceID':0,'NewTransportSettings':settings,'CurrentAVTransportURI':uri})
        else:act('Play',{'InstanceID':0,'Speed':'1'})
        time.sleep(10)
        act('GetTransportInfo',{'InstanceID':0})
    except Exception as e:error=str(e)
    finally:
        steps=[]
        if a.group_member:steps.append(('BecomeCoordinatorOfStandaloneGroup',{'InstanceID':0},AV,'AVTransport'))
        steps.append(('SetAVTransportURI',{'InstanceID':0,'CurrentURI':media['CurrentURI'],'CurrentURIMetaData':media['CurrentURIMetaData']},AV,'AVTransport'))
        if state['CurrentTransportState'] in ('PLAYING','PAUSED_PLAYBACK'):
            steps.append(('Play',{'InstanceID':0,'Speed':'1'},AV,'AVTransport'))
            if state['CurrentTransportState']=='PAUSED_PLAYBACK':steps.append(('Pause',{'InstanceID':0},AV,'AVTransport'))
        else:steps.append(('Stop',{'InstanceID':0},AV,'AVTransport'))
        steps.append(('SetMute',{'InstanceID':0,'Channel':'Master','DesiredMute':mute['CurrentMute']},RC,'RenderingControl'))
        for name,args,path,service in steps:
            try:
                if name=='Pause':time.sleep(1)
                act(name,args,path,service)
            except Exception as e:restore.append(str(e))
        for target in types:udp.sendto(packet(target,True,True),('239.255.255.250',1900))
        stop.set();server.shutdown();server.server_close();time.sleep(.3);udp.close()
        for srv in tls_servers:srv.shutdown();srv.server_close()
        result={'snapshot':snapshot,'events':events,'actions':log,'error':error,'restore_errors':restore}
        out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'events':events,'error':error,'restore_errors':restore},indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--allow-other-source',action='store_true')
    p.add_argument('--group-member',action='store_true')
    p.add_argument('--tls-cert')
    p.add_argument('--tls-key')
    for k in ['source','receiver','household','output']:p.add_argument('--'+k,required=True)
    run(p.parse_args())
