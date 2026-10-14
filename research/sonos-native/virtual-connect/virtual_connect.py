#!/usr/bin/env python3
"""Experimental Sonos discovery/setup observer. No enrollment or audio backend."""
import argparse, collections, http.server, ipaddress, json, pathlib, signal, socket
import ssl, subprocess, threading, time, urllib.request, urllib.parse, uuid
import xml.etree.ElementTree as E

DEVICE = 'urn:schemas-upnp-org:device:ZonePlayer:1'
SCHEMA = 'urn:schemas-upnp-org:device-1-0'
SOAP = 'http://schemas.xmlsoap.org/soap/envelope/'
E.register_namespace('s', SOAP)
SERVICES = {
    'DeviceProperties': {'GetHouseholdID': ['CurrentHouseholdID'],
        'GetZoneAttributes': ['CurrentZoneName', 'CurrentIcon', 'CurrentConfiguration'],
        'GetZoneInfo': ['SerialNumber','SoftwareVersion','DisplaySoftwareVersion','HardwareVersion','IPAddress','MACAddress','CopyrightInfo','ExtraInfo','HTAudioIn','Flags']},
    'ZoneGroupTopology': {'GetZoneGroupState': ['ZoneGroupState']},
    'AudioIn': {'GetAudioInputAttributes': ['CurrentName','CurrentIcon']},
}
PAGE = b'''<!doctype html><meta charset="utf-8"><title>Virtual Connect</title>
<style>body{font:17px system-ui;max-width:950px;margin:45px auto;padding:20px;background:#101820;color:#e4edf5}h1{color:#64dbc2}pre{white-space:pre-wrap;background:#1b2935;padding:20px;border-radius:12px}small{color:#afc2ce}</style>
<h1>Virtual Connect</h1><p>Discovery and setup observer</p>
<p>See the mode below for discovery status. The reference-profile test uses a real
Connect's public description with a separate virtual identity. Enrollment and audio
are not implemented; the earlier iOS crash fix remains unverified.</p><small>Requests are logged without bodies, credentials or query values. Stop from the launcher with Ctrl-C.</small>
<pre id="status">Loading...</pre><script>async function tick(){try{let r=await fetch('/status');document.getElementById('status').textContent=JSON.stringify(await r.json(),null,2)}catch(e){document.getElementById('status').textContent='Prototype stopped or unreachable.'}}tick();setInterval(tick,2000)</script>'''


def xml_response(service, name, values):
    root=E.Element('{'+SOAP+'}Envelope');body=E.SubElement(root,'{'+SOAP+'}Body')
    r=E.SubElement(body,'{urn:schemas-upnp-org:service:'+service+':1}'+name+'Response')
    for k,v in values.items(): E.SubElement(r,k).text=str(v)
    return E.tostring(root,encoding='utf-8',xml_declaration=True)


def fault(code=401):
    root=E.Element('{'+SOAP+'}Envelope');b=E.SubElement(root,'{'+SOAP+'}Body');f=E.SubElement(b,'{'+SOAP+'}Fault')
    E.SubElement(f,'faultcode').text='s:Client';E.SubElement(f,'faultstring').text='UPnPError'
    d=E.SubElement(f,'detail');u=E.SubElement(d,'UPnPError',xmlns='urn:schemas-upnp-org:control-1-0')
    E.SubElement(u,'errorCode').text=str(code);E.SubElement(u,'errorDescription').text='Action not implemented by experimental source'
    return E.tostring(root)


def descriptor(ip, name, identity):
    root=E.Element('root',xmlns=SCHEMA);spec=E.SubElement(root,'specVersion')
    E.SubElement(spec,'major').text='1';E.SubElement(spec,'minor').text='0'
    d=E.SubElement(root,'device')
    vals={'deviceType':DEVICE,'friendlyName':name,'manufacturer':'Sonos-compatible research prototype',
          'modelNumber':'ZP90','modelName':'Virtual Connect (Experimental)',
          'modelDescription':'Independent discovery prototype; enrollment not implemented',
          'softwareVersion':'86.10-80260','swGen':'2','hardwareVersion':'1.0.0.0-0.0',
          'serialNum':identity['mac'].replace(':','-')+':0','MACAddress':identity['mac'],
          'UDN':'uuid:'+identity['uuid'],'roomName':name,'displayName':'Virtual Connect',
          'zoneType':'1','minCompatibleVersion':'85.0-00000','legacyCompatibleVersion':'58.0-00000',
          'apiVersion':'1.54.1','minApiVersion':'1.1.0','displayVersion':'17.2.7',
          # Keep numeric discovery fields explicit. Do not copy real hardware
          # feature bits: the prototype has not implemented those capabilities.
          'nsVersion':'42','feature1':'0x00000000','feature2':'0x00000000',
          'feature3':'0x00000000','feature4':'0x00000000','seriesid':'C100',
          'variant':'0','internalSpeakerSize':'-1','memory':'0','flash':'0',
          'flashRepartitioned':'0','ampOnTime':'0','retailMode':'0',
          'SSLPort':'1443','securehhSSLPort':'1843'}
    for k,v in vals.items():E.SubElement(d,k).text=v
    sl=E.SubElement(d,'serviceList')
    for svc in SERVICES:
        s=E.SubElement(sl,'service')
        for k,v in {'serviceType':'urn:schemas-upnp-org:service:'+svc+':1',
            'serviceId':'urn:upnp-org:serviceId:'+svc,'controlURL':'/'+svc+'/Control',
            'eventSubURL':'/'+svc+'/Event','SCPDURL':'/xml/'+svc+'1.xml'}.items():E.SubElement(s,k).text=v
    return E.tostring(root,encoding='utf-8',xml_declaration=True)


def service_description(svc):
    r=E.Element('scpd',xmlns='urn:schemas-upnp-org:service-1-0');spec=E.SubElement(r,'specVersion')
    E.SubElement(spec,'major').text='1';E.SubElement(spec,'minor').text='0'
    actions=E.SubElement(r,'actionList');states=E.SubElement(r,'serviceStateTable');seen=set()
    for name,args in SERVICES[svc].items():
        action=E.SubElement(actions,'action');E.SubElement(action,'name').text=name
        al=E.SubElement(action,'argumentList')
        for arg in args:
            a=E.SubElement(al,'argument')
            for k,v in [('name',arg),('direction','out'),('relatedStateVariable',arg)]:E.SubElement(a,k).text=v
            if arg not in seen:
                seen.add(arg);state=E.SubElement(states,'stateVariable',sendEvents='no')
                E.SubElement(state,'name').text=arg;E.SubElement(state,'dataType').text='string'
    return E.tostring(r)


def reference_descriptor(raw, ip, name, identity):
    """Preserve the reference structure, replacing every real device identity."""
    root=E.fromstring(raw)
    device=root.find('{*}device')
    original_uuid=device.find('{*}UDN').text.removeprefix('uuid:')
    replacements={original_uuid:identity['uuid']}
    for tag,new in [('serialNum',identity['mac'].replace(':','-')+':0'),
                    ('MACAddress',identity['mac'])]:
        old=device.find('{*}'+tag)
        if old is not None and old.text:replacements[old.text]=new
    for elem in root.iter():
        for old,new in replacements.items():
            if elem.text:elem.text=elem.text.replace(old,new)
            for k,v in list(elem.attrib.items()):elem.set(k,v.replace(old,new))
        tag=elem.tag.split('}')[-1]
        if tag=='friendlyName':elem.text=name+' - '+identity['uuid']
        elif tag=='roomName':elem.text=name
        elif tag=='IPAddress':elem.text=ip
        elif tag=='URLBase':elem.text='http://'+ip+':1400/'
    E.register_namespace('',SCHEMA)
    return E.tostring(root,encoding='utf-8',xml_declaration=True)


class App:
    def __init__(self,a):
        self.a=a;self.stop=threading.Event();self.lock=threading.Lock();self.events=collections.deque(maxlen=100)
        self.state=pathlib.Path(a.state).resolve();self.state.mkdir(parents=True,exist_ok=True,mode=0o700)
        path=self.state/'identity.json'
        if path.exists():self.identity=json.loads(path.read_text())
        else:
            mac='02:'+':'.join('%02X'%v for v in uuid.uuid4().bytes[:5])
            self.identity={'mac':mac,'uuid':'RINCON_'+mac.replace(':','')+'01400'}
            path.write_text(json.dumps(self.identity,indent=2));path.chmod(0o600)
        self.resources={}
        if getattr(a,'profile',None):
            profile=pathlib.Path(a.profile).resolve()
            self.descriptor=reference_descriptor((profile/'device.xml').read_bytes(),a.bind,a.name,self.identity)
            for route,filename in json.loads((profile/'resources.json').read_text()).items():
                path=(profile/filename).resolve()
                if path.parent!=profile:raise ValueError('Invalid profile resource path')
                self.resources[route]=path.read_bytes()
        else:self.descriptor=descriptor(a.bind,a.name,self.identity)
        self.device_fields={e.tag.split('}')[-1]:e.text or '' for e in E.fromstring(self.descriptor).find('{*}device') if not len(e)}
        self.servers=[];self.udp=None;self.setup_udp=None
        self.logfile=self.state/('events-'+time.strftime('%Y%m%d-%H%M%S')+'.jsonl')
        self.topology={'state':'not checked'}
        self.household=a.household or ''
        self.boot=str(int(time.time()))

    def event(self,kind,**fields):
        row={'time':time.strftime('%H:%M:%S'),'kind':kind,**fields}
        with self.lock:
            self.events.append(row)
            with self.logfile.open('a') as f:f.write(json.dumps(row)+'\n')

    def status(self):
        with self.lock:return {'name':self.a.name,'identity':self.identity['uuid'],
            'descriptor_profile':'reference Connect' if getattr(self.a,'profile',None) else 'minimal experimental',
            'mode':('household discovery' if self.household else 'unpaired discovery experiment') if self.a.advertise else 'local inspection; discovery disabled',
            'enrolled':False,'audio_available':False,'observed_by_speaker':self.topology,
            'events':list(self.events)[-30:]}

    def start_http(self):
        app=self
        class Handler(http.server.BaseHTTPRequestHandler):
            server_version='VirtualConnect/0.1';sys_version=''
            def log_message(self,*args):pass
            def setup(self):
                super().setup();self.connection.settimeout(5)
            def reply(self,body=b'',code=200,ctype='text/xml'):
                self.send_response(code);self.send_header('Content-Type',ctype)
                self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
                self.end_headers();self.wfile.write(body)
            def record(self,**extra):
                # Values and bodies may contain provisioning secrets: never log them.
                path=urllib.parse.urlsplit(self.path).path
                app.event('request',method=self.command,path=path,peer=self.client_address[0],**extra)
            def do_GET(self):
                path=urllib.parse.urlsplit(self.path).path
                if path=='/':return self.reply(PAGE,ctype='text/html; charset=utf-8')
                if path=='/status':return self.reply(json.dumps(app.status()).encode(),ctype='application/json')
                self.record()
                if path=='/xml/device_description.xml':return self.reply(app.descriptor)
                if path in app.resources:
                    return self.reply(app.resources[path],ctype='image/png' if path.endswith('.png') else 'text/xml')
                for svc in SERVICES:
                    if path=='/xml/'+svc+'1.xml':return self.reply(service_description(svc))
                self.reply(b'',404)
            def do_POST(self):
                try:n=int(self.headers.get('Content-Length','0'))
                except ValueError:return self.reply(b'',400)
                if n<0 or n>65536 or self.headers.get('Transfer-Encoding'):return self.reply(b'',413)
                body=self.rfile.read(n)
                if b'<!DOCTYPE' in body or b'<!ENTITY' in body:return self.reply(b'',400)
                try:
                    root=E.fromstring(body);container=root.find('{'+SOAP+'}Body')
                    action=list(container)[0];name=action.tag.split('}')[-1]
                    ns=action.tag.split('}')[0].lstrip('{');svc=ns.split(':')[-2]
                except (E.ParseError,TypeError,IndexError):
                    self.record(outcome='unsupported request');return self.reply(fault(),500)
                self.record(action=name,argument_names=[e.tag.split('}')[-1] for e in action])
                values={'GetHouseholdID':{'CurrentHouseholdID':app.household},
                    'GetZoneAttributes':{'CurrentZoneName':app.a.name,'CurrentIcon':'x-rincon-roomicon:generic','CurrentConfiguration':'0'},
                    'GetZoneInfo':{'SerialNumber':app.identity['mac'].replace(':','-')+':0',
                        'SoftwareVersion':'86.10-80260','DisplaySoftwareVersion':'17.2.7','HardwareVersion':'1.0',
                        'IPAddress':app.a.bind,'MACAddress':app.identity['mac'],'CopyrightInfo':'Experimental virtual source',
                        'ExtraInfo':'','HTAudioIn':'0','Flags':'0'},
                    'GetZoneGroupState':{'ZoneGroupState':'<ZoneGroupState><ZoneGroups/></ZoneGroupState>'},
                    'GetAudioInputAttributes':{'CurrentName':app.a.name,'CurrentIcon':'AudioComponent'}}
                for response,field in [('SoftwareVersion','softwareVersion'),('DisplaySoftwareVersion','displayVersion'),('HardwareVersion','hardwareVersion')]:
                    values['GetZoneInfo'][response]=app.device_fields[field]
                if self.path!='/'+svc+'/Control' or name not in SERVICES.get(svc,{}):return self.reply(fault(),500)
                self.reply(xml_response(svc,name,values[name]))
            def do_SUBSCRIBE(self):
                self.record(outcome='eventing not implemented');self.reply(b'',501)
            def do_UNSUBSCRIBE(self):self.record();self.reply(b'',412)
        cert=self.state/'experimental.crt';key=self.state/'experimental.key'
        if not cert.exists() or not key.exists():
            subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),
                '-out',str(cert),'-days','30','-subj','/CN=Virtual Connect Experimental'],check=True,capture_output=True)
            key.chmod(0o600)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        # Both live reference speakers negotiate TLS 1.2 on port 1443.
        # Match that protocol before attributing the client's disconnect to trust.
        context.minimum_version=ssl.TLSVersion.TLSv1_2
        context.maximum_version=ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert,key)
        # Log protocol stages only, never handshake payloads, keys or credentials.
        if hasattr(context,'_msg_callback'):
            def tls_stage(conn,direction,version,content_type,message_type,data):
                if int(content_type) not in (21,22):return
                try:peer=conn.getpeername()[0]
                except OSError:peer='disconnected'
                fields={'peer':peer,'direction':direction,'version':str(version),
                        'message':getattr(message_type,'name',str(message_type))}
                if int(content_type)==21 and len(data)==2:fields['alert_code']=data[1]
                app.event('tls_stage',**fields)
            context._msg_callback=tls_stage
        class Server(http.server.ThreadingHTTPServer):
            daemon_threads=True
            def get_request(self):
                conn,peer=super().get_request();conn.settimeout(3)
                if self.server_port==1400:return conn,peer
                try:
                    conn=context.wrap_socket(conn,server_side=True)
                    app.event('tls',peer=peer[0],port=self.server_port,outcome='handshake accepted')
                    return conn,peer
                except (ssl.SSLError,OSError) as e:
                    app.event('tls',peer=peer[0],port=self.server_port,outcome=getattr(e,'reason',type(e).__name__))
                    conn.close();raise OSError('TLS handshake failed')
        for port in ((1400,1443,1843) if self.a.advertise else (1400,)):
            server=Server((self.a.bind if self.a.advertise else '127.0.0.1',port),Handler);self.servers.append(server)
            threading.Thread(target=server.serve_forever,daemon=True).start()

    def packet(self,target,notify=False,bye=False):
        uid='uuid:'+self.identity['uuid'];usn=uid if target==uid else uid+'::'+target
        h=['NOTIFY * HTTP/1.1' if notify else 'HTTP/1.1 200 OK']
        if notify:h+=['HOST: 239.255.255.250:1900','NT: '+target,'NTS: ssdp:'+('byebye' if bye else 'alive')]
        else:h+=['ST: '+target,'EXT:']
        h+=['USN: '+usn,'LOCATION: http://'+self.a.bind+':1400/xml/device_description.xml',
            'CACHE-CONTROL: max-age=60','SERVER: Linux UPnP/1.0 Sonos/86.10-80260 (ZP90)',
            'X-RINCON-BOOTSEQ: '+self.boot]
        if self.household:h+=['X-RINCON-HOUSEHOLD: '+self.household]
        return ('\r\n'.join(h)+'\r\n\r\n').encode()

    def advertise(self,bye=False):
        if not self.udp:return
        for target in self.targets:
            self.udp.sendto(self.packet(target,True,bye),('239.255.255.250',1900))

    def start_ssdp(self):
        self.targets=[DEVICE,'upnp:rootdevice','uuid:'+self.identity['uuid']]
        self.udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM,socket.IPPROTO_UDP)
        self.udp.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);self.udp.bind(('',1900))
        self.udp.setsockopt(socket.IPPROTO_IP,socket.IP_ADD_MEMBERSHIP,socket.inet_aton('239.255.255.250')+socket.inet_aton(self.a.bind))
        self.udp.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_IF,socket.inet_aton(self.a.bind))
        self.udp.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_TTL,2);self.udp.settimeout(.5)
        def listen():
            while not self.stop.is_set():
                try:data,peer=self.udp.recvfrom(8192)
                except socket.timeout:continue
                except OSError:break
                if not data.startswith(b'M-SEARCH '):continue
                fields={}
                for line in data.decode(errors='replace').split('\r\n')[1:]:
                    k,sep,v=line.partition(':')
                    if sep:fields[k.strip().upper()]=v.strip()
                for target in self.targets:
                    if fields.get('ST') in (target,'ssdp:all'):self.udp.sendto(self.packet(target),peer)
        threading.Thread(target=listen,daemon=True).start();self.advertise()

    def start_setup_observer(self):
        # The older netstartd binds UDP 6969. Until message semantics are
        # established, observe only: never acknowledge configuration or store it.
        self.setup_udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self.setup_udp.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        self.setup_udp.bind(('',6969));self.setup_udp.settimeout(.5)
        def listen():
            while not self.stop.is_set():
                try:data,peer=self.setup_udp.recvfrom(65535)
                except socket.timeout:continue
                except OSError:break
                self.event('setup_udp',peer=peer[0],bytes=len(data),
                           header_flags=data[0] if data else None,
                           message_type=data[1] if len(data)>1 else None,
                           outcome='observed only; no response sent')
        threading.Thread(target=listen,daemon=True).start()

    def observe(self):
        if not self.a.observe:return
        req=urllib.request.Request('http://'+self.a.observe+':1400/ZoneGroupTopology/Control',
            data=b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body><u:GetZoneGroupState xmlns:u="urn:schemas-upnp-org:service:ZoneGroupTopology:1"/></s:Body></s:Envelope>',
            headers={'Content-Type':'text/xml','SOAPACTION':'"urn:schemas-upnp-org:service:ZoneGroupTopology:1#GetZoneGroupState"'})
        try:
            with urllib.request.urlopen(req,timeout=3) as r:root=E.fromstring(r.read(2000000))
            state=next(e.text for e in root.iter() if e.tag.split('}')[-1]=='ZoneGroupState')
            root=E.fromstring(state);found=[]
            for parent in root.iter():
                for child in parent:
                    if child.get('UUID')==self.identity['uuid']:
                        found.append({'section':parent.tag,'reason':child.get('QuarantineReason'),
                            'registration_state':child.get('SecureRegState')})
            value={'state':'seen' if found else 'not listed','entries':found}
        except Exception as e:value={'state':'check failed','error_type':type(e).__name__}
        with self.lock:self.topology=value

    def run(self):
        try:
            self.start_http()
            if self.a.advertise:self.start_setup_observer();self.start_ssdp()
            host=self.a.bind if self.a.advertise else '127.0.0.1'
            print('Virtual Connect running: http://'+host+':1400',flush=True)
            print('Experimental discovery enabled.' if self.a.advertise else 'Local inspection only: no LAN listeners or discovery announcements.',flush=True)
            print('Enrollment and audio are not implemented. Ctrl-C stops.',flush=True)
            end=time.monotonic()+self.a.minutes*60;next_ad=0
            while not self.stop.wait(1) and time.monotonic()<end:
                if time.monotonic()>=next_ad:
                    if self.a.advertise:self.advertise();self.observe()
                    next_ad=time.monotonic()+20
        finally:
            self.stop.set()
            try:self.advertise(True)
            except OSError:pass
            if self.udp:self.udp.close()
            if self.setup_udp:self.setup_udp.close()
            for server in self.servers:server.shutdown();server.server_close()
            self.event('stopped');print('Stopped; discovery advertisements withdrawn.',flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bind',required=True,help='Mac LAN IPv4 address')
    p.add_argument('--advertise',action='store_true',help='Enable experimental LAN discovery; prior iOS crash is unresolved')
    p.add_argument('--profile',help='Local reference folder containing device.xml and resources.json')
    p.add_argument('--observe',help='Optional real speaker IP: read-only topology checks')
    p.add_argument('--household',default='',help='Optional existing household ID; omission tests unpaired discovery')
    p.add_argument('--name',default='Virtual Connect Lab');p.add_argument('--minutes',type=int,default=30)
    p.add_argument('--state',default=str(pathlib.Path(__file__).parent/'state'))
    a=p.parse_args();ipaddress.IPv4Address(a.bind)
    if a.observe:ipaddress.IPv4Address(a.observe)
    if not 1<=a.minutes<=120:p.error('Duration must be 1–120 minutes')
    if any(c in a.household for c in '\r\n'):p.error('Invalid household')
    app=App(a)
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:app.stop.set())
    app.run()

if __name__=='__main__':main()
