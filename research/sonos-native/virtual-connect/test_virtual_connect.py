import tempfile,unittest,types,xml.etree.ElementTree as E
from virtual_connect import App,descriptor,service_description,xml_response,fault,SERVICES
class Tests(unittest.TestCase):
 def test_persistent_identity_and_discovery(self):
  with tempfile.TemporaryDirectory() as d:
   args=types.SimpleNamespace(state=d,bind='127.0.0.1',household='',name='Lab',advertise=False)
   a=App(args);b=App(args)
   self.assertEqual(a.identity,b.identity)
   self.assertNotIn(b'X-RINCON-HOUSEHOLD',a.packet('upnp:rootdevice'))
   self.assertIn(b'ssdp:byebye',a.packet('upnp:rootdevice',True,True))
   self.assertFalse(a.status()['enrolled'])
   self.assertFalse(a.status()['audio_available'])
   self.assertIn('discovery disabled',a.status()['mode'])
 def test_numeric_descriptor_fields(self):
  x=E.fromstring(descriptor('127.0.0.1','Lab',{'uuid':'TEST','mac':'02:00:00:00:00:01'}))
  for field in ('swGen','zoneType','nsVersion','variant','internalSpeakerSize','memory','flash','flashRepartitioned','ampOnTime','retailMode','SSLPort','securehhSSLPort'):
   value=x.find('.//{*}'+field)
   self.assertIsNotNone(value,field)
   int(value.text,10)
  for field in ('feature1','feature2','feature3','feature4'):
   self.assertEqual(int(x.find('.//{*}'+field).text,16),0)
  self.assertEqual(x.find('.//{*}zoneType').text,'1')
 def test_xml_contract(self):
  x=E.fromstring(descriptor('127.0.0.1','Kitchen & Hall',{'uuid':'TEST','mac':'02:00:00:00:00:01'}))
  self.assertEqual(x.find('.//{*}roomName').text,'Kitchen & Hall')
  for svc in SERVICES:E.fromstring(service_description(svc))
  r=E.fromstring(xml_response('DeviceProperties','GetZoneAttributes',{'CurrentZoneName':'A & B'}))
  self.assertEqual(r.find('.//CurrentZoneName').text,'A & B')
  self.assertIn(b'xmlns:s=',fault())
  self.assertEqual(E.fromstring(fault()).find('.//{*}errorCode').text,'401')
if __name__=='__main__':unittest.main()
