import urllib.request,urllib.error,xml.etree.ElementTree as E,json,sys

def call(ip,path,service,action,args,*,headers=None):
 ns='urn:schemas-upnp-org:service:'+service+':1'
 root=E.Element('{http://schemas.xmlsoap.org/soap/envelope/}Envelope',{'{http://schemas.xmlsoap.org/soap/envelope/}encodingStyle':'http://schemas.xmlsoap.org/soap/encoding/'})
 body=E.SubElement(root,'{http://schemas.xmlsoap.org/soap/envelope/}Body');a=E.SubElement(body,'{'+ns+'}'+action)
 for k,v in args.items():E.SubElement(a,k).text=str(v)
 request_headers={'Content-Type':'text/xml; charset="utf-8"','SOAPACTION':'"'+ns+'#'+action+'"'}
 request_headers.update(headers or {})
 req=urllib.request.Request('http://'+ip+':1400'+path,data=E.tostring(root),headers=request_headers)
 try:
  with urllib.request.urlopen(req,timeout=8) as r:code=r.status;data=r.read()
 except urllib.error.HTTPError as e:code=e.code;data=e.read()
 return {'http_status':code,'xml':data.decode()}
if __name__=='__main__':print(json.dumps(call(*sys.argv[1:5],json.loads(sys.argv[5])),indent=2))
