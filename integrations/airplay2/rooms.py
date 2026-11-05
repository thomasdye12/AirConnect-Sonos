#!/usr/bin/env python3
"""Generate per-room AirPlay 2 configuration from a saved Sonos topology.

Python 3.4+. Does not start services or change speakers. Keep generated files
private. Rerunning preserves ports by UUID, including reservations for old rooms.
"""
import argparse
import hashlib
import ipaddress
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from urllib.parse import urlparse


def identity(uid):
    if not re.fullmatch(r'RINCON_[0-9A-F]{17}', uid):
        raise ValueError('Invalid Sonos UUID')
    return uid[7:].lower()


def discover(xml, helper):
    identity(helper)
    root = ET.fromstring(xml)
    rooms, seen, names = [], set(), set()
    for node in root.iter('ZoneGroupMember'):
        if node.get('Invisible') == '1':
            continue
        uid = node.get('UUID', '')
        key = identity(uid)
        if uid in seen:
            raise ValueError('Duplicate visible room identity')
        seen.add(uid)
        if uid == helper:
            continue
        name = node.get('ZoneName', '').strip()
        if not name or any(ord(c) < 32 for c in name):
            raise ValueError('Invalid room name')
        advertised = name + ' (AirPlay 2)'
        if len(advertised.encode('utf-8')) > 63 or advertised in names:
            raise ValueError('Duplicate or overly long advertised room name')
        names.add(advertised)
        url = urlparse(node.get('Location', ''))
        ipaddress.IPv4Address(url.hostname)
        if url.scheme != 'http' or url.port != 1400 or url.username or url.password or url.query or url.fragment or url.path != '/xml/device_description.xml':
            raise ValueError('Unexpected Sonos description URL')
        rooms.append(dict(uuid=uid, key=key, name=name, advertised_name=advertised,
                          address=url.hostname, receiver_url=url.geturl(),
                          bonded=bool(node.get('ChannelMapSet') or node.get('HTSatChanMapSet'))))
    if helper not in seen:
        raise ValueError('Configured helper is absent from the visible topology')
    if not rooms:
        raise ValueError('No destination rooms found')
    return sorted(rooms, key=lambda r: r['uuid'])


def plan(rooms, previous, capacity, base_port=7200):
    if not 1 <= capacity <= 128 or len(rooms) > capacity:
        raise ValueError('Room count exceeds verified timing-daemon capacity')
    if previous and previous.get('version') != 1:
        raise ValueError('Unsupported previous manifest')
    assignments = dict(previous.get('ports', {}))
    for uid, port in assignments.items():
        identity(uid)
        if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
            raise ValueError('Invalid reserved TCP port')
    used = set(assignments.values())
    if len(used) != len(assignments):
        raise ValueError('Duplicate reserved TCP ports')
    output, device_ids = [], set()
    for room in rooms:
        uid = room['uuid']
        if uid not in assignments:
            port = base_port
            while port in used:
                port += 1
            if not 1024 <= port <= 65535:
                raise ValueError('No valid port available')
            assignments[uid] = port
            used.add(port)
        entry = dict(room)
        device = '02' + hashlib.sha256(('airconnect-ap2:' + uid).encode()).hexdigest()[:10]
        if device in device_ids:
            raise ValueError('AirPlay device ID collision')
        device_ids.add(device)
        entry.update(port=assignments[uid], device_id=device,
                     timing_interface='/nqptp-ac-' + room['key'])
        output.append(entry)
    return dict(version=1, timing_capacity=capacity, ports=assignments, rooms=output)


def config(room, worker, helper_path, local_ip, speaker_volume):
    q = lambda value: json.dumps(value, ensure_ascii=False)
    return '''general = {
 name = %s;
 service_type = "airplay2";
 output_backend = "airconnect";
 mdns_backend = "avahi";
 port = %d;
 airplay_device_id = 0x%sL;
 nqptp_shared_memory_interface_name = %s;
};
metadata = { enabled = "no"; };
airconnect = {
 worker = %s;
 helper = %s;
 local_ip = %s;
 receiver_url = %s;
 receiver_udn = %s;
 speaker_volume = %d;
 muted = false;
};
''' % (q(room['advertised_name']), room['port'], room['device_id'],
       q(room['timing_interface']), q(worker), q(helper_path), q(local_ip),
       q(room['receiver_url']), q('uuid:' + room['uuid']), speaker_volume)


def atomic_write(path, text):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory, delete=False) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--topology', required=True, help='Saved GetZoneGroupState XML')
    p.add_argument('--helper-uuid', required=True)
    p.add_argument('--helper-config', required=True)
    p.add_argument('--worker', required=True)
    p.add_argument('--local-ip', required=True)
    p.add_argument('--capacity', required=True, type=int, help='Verified NQPTP client capacity')
    p.add_argument('--speaker-volume', type=int, default=100)
    p.add_argument('--output', required=True)
    p.add_argument('--write', action='store_true', help='Write configs and manifest; otherwise print plan only')
    a = p.parse_args()
    ipaddress.IPv4Address(a.local_ip)
    if not 0 <= a.speaker_volume <= 100:
        p.error('Speaker volume must be 0..100')
    for path in (a.helper_config, a.worker):
        if not os.path.isabs(path) or any(ord(c) < 32 for c in path):
            p.error('Worker and helper paths must be absolute without control characters')
    manifest_path = os.path.join(a.output, 'manifest.json')
    previous = {}
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            previous = json.load(f)
    with open(a.topology) as f:
        xml = f.read(1024 * 1024 + 1)
    if len(xml) > 1024 * 1024:
        p.error('Topology exceeds limit')
    manifest = plan(discover(xml, a.helper_uuid), previous, a.capacity)
    manifest.update(helper_uuid=a.helper_uuid, speaker_volume=a.speaker_volume)
    rendered = [(r['key'] + '.conf', config(r, a.worker, a.helper_config, a.local_ip, a.speaker_volume)) for r in manifest['rooms']]
    if a.write:
        for name, contents in rendered:
            atomic_write(os.path.join(a.output, name), contents)
        atomic_write(manifest_path, json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
