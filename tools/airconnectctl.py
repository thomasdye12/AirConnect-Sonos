#!/usr/bin/env python3
"""Local bridge management. Python 3.4+; experimental transport tests need Python 3.8+."""
import argparse
import json
import ipaddress
import os
import re
import subprocess
import sys
import time
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

LIMIT = 1024 * 1024


def validate_helper(data):
    if not isinstance(data, dict) or data.get('version') != 1:
        raise ValueError('Unsupported helper configuration')
    helper = data.get('helper', {})
    if not isinstance(helper, dict) or not re.fullmatch(r'RINCON_[0-9A-F]{17}', helper.get('uuid', '')):
        raise ValueError('Invalid helper device ID')
    ipaddress.IPv4Address(helper.get('address', ''))
    if not isinstance(helper.get('name'), str) or not helper['name'].strip():
        raise ValueError('Invalid helper name')
    return helper


def load_helper(path):
    with open(path, 'rb') as stream:
        data = load_json(stream)
    return validate_helper(data)


def save_helper(path, address):
    address = str(ipaddress.IPv4Address(address))
    with urllib.request.urlopen('http://' + address + ':1400/xml/device_description.xml', timeout=5) as response:
        raw = response.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Helper description too large')
    root = ET.fromstring(raw)
    device = next((e for e in root if e.tag.split('}')[-1] == 'device'), None)
    if device is None:
        raise ValueError('Missing helper device description')
    fields = {e.tag.split('}')[-1]: e.text or '' for e in device}
    uid = fields.get('UDN', '')
    if not uid.startswith('uuid:'):
        raise ValueError('Invalid helper identity')
    data = {'version': 1, 'helper': {'address': address, 'uuid': uid[5:], 'name': fields.get('roomName', '')}}
    helper = validate_helper(data)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=directory, prefix='.helper-', delete=False) as stream:
            temporary = stream.name
            json.dump(data, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary): os.unlink(temporary)
    return helper


def set_native_mode(config, helper_path, enabled, muted=False, sync_offset=None):
    if sync_offset is not None and not -1000 <= sync_offset <= 5000:
        raise ValueError("Native sync offset must be -1000..5000 ms")
    if enabled:
        load_helper(helper_path)
    tree = ET.parse(config)
    root = tree.getroot()
    if root.tag != 'airupnp':
        raise ValueError('Expected an AirUPnP configuration')
    common = root.find('common')
    if common is None:
        common = ET.SubElement(root, 'common')
    for parent, name, value in ((root, 'sonos_native_helper', os.path.abspath(helper_path)),
                                (common, 'native_udp', str(int(enabled))),
                                (common, 'native_muted', str(int(muted)))):
        node = parent.find(name)
        if node is None:
            node = ET.SubElement(parent, name)
        node.text = value
    if sync_offset is not None:
        node = common.find('native_sync_offset_ms')
        if node is None:
            node = ET.SubElement(common, 'native_sync_offset_ms')
        node.text = str(sync_offset)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=os.path.dirname(os.path.abspath(config)), delete=False) as stream:
            temporary = stream.name
            tree.write(stream, encoding='UTF-8', xml_declaration=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, os.stat(config).st_mode & 0o777)
        os.replace(temporary, config)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def load_json(stream):
    body = stream.read(LIMIT + 1)
    if len(body) > LIMIT:
        raise ValueError('Room response exceeds 1 MiB')
    return json.loads(body.decode('utf-8'))


def valid_rooms(zones, prefix='', suffix=' (Sonos)'):
    if not isinstance(zones, list) or not 1 <= len(zones) <= 128:
        raise ValueError('Invalid room list')
    rooms, seen = [], set()
    for zone in zones:
        c = zone.get('coordinator', {})
        uid, name = c.get('uuid'), c.get('roomName')
        if not isinstance(uid, str) or not uid.startswith('RINCON_') or not isinstance(name, str) or not name or uid in seen:
            raise ValueError('Invalid or duplicate coordinator')
        seen.add(uid)
        rooms.append({'name': prefix + name + suffix, 'uuid': uid})
    return rooms


def room_list(api, cache, prefix, suffix):
    if not api.startswith('http://'):
        raise ValueError('Configure a local http:// Sonos /zones API')
    try:
        with urllib.request.urlopen(api, timeout=5) as response:
            rooms = valid_rooms(load_json(response), prefix, suffix)
        return {'source': 'live API', 'rooms': rooms}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        if not cache:
            raise RuntimeError('Room API unavailable; no cache configured: ' + str(exc))
        with open(cache, 'rb') as stream:
            data = load_json(stream)
        age = time.time() - data.get('fetched_at', 0)
        if data.get('version') != 1 or data.get('api') != api or not 0 <= age <= 86400:
            raise ValueError('Cache expired, from the future, or for another API')
        return {'source': 'cached; group changes may not be reflected',
                'age_seconds': int(age), 'rooms': valid_rooms(data['zones'], prefix, suffix)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/var/airplay_sonos/Config.xml')
    parser.add_argument('--api', help='Override /zones URL for rooms command')
    parser.add_argument('--helper-config', help='Native helper JSON; defaults beside --config as native-helper.json')
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('status', help='Local systemd status and configuration (read only)')
    sub.add_parser('rooms', help='Validated API coordinator names, with cache fallback')
    sub.add_parser('restart', help='Restart the local bridge and refresh its startup room list')
    helper = sub.add_parser('helper-set', help='Verify and save the helper for experimental native UDP setup')
    helper.add_argument('--address', required=True, help='IPv4 address of the chosen Sonos helper')
    sub.add_parser('helper-show', help='Show the configured native helper; no speaker changes')
    mode = sub.add_parser('native-mode', help='Configure native AirPlay output; restart bridge to apply')
    mode.add_argument('--enabled', type=int, choices=(0, 1), required=True)
    mode.add_argument('--sync-offset-ms', type=int, choices=range(-1000, 5001), metavar='-1000..5000', help='Local A/V calibration; positive delays audio, omitted preserves existing value')
    mode.add_argument('--muted', action='store_true', help='Keep native receivers muted for validation')
    clip = sub.add_parser('clip-test', help='Experimental bounded SILENT HTTP WAV test, not AirPlay')
    clip.add_argument('--receiver', required=True)
    clip.add_argument('--receiver-id', required=True)
    clip.add_argument('--output', required=True, help='Private JSON result file')
    clip.add_argument('--seconds', type=int, choices=range(1, 61), default=12, metavar='1..60')
    clip.add_argument('--streaming', action='store_true')
    udp = sub.add_parser('udp-test', help='Experimental bounded UDP test with a stopped helper; muted by default')
    for name in ('receiver', 'receiver-id', 'output'):
        udp.add_argument('--' + name, required=True)
    udp.add_argument('--coordinator', help='Override saved helper address; requires --coordinator-id')
    udp.add_argument('--coordinator-id', help='Override saved helper UUID; requires --coordinator')
    udp.add_argument('--lock-timeout', type=float, default=15, help='Maximum wait for receiver/helper ownership in seconds')
    udp.add_argument('--mode', choices=('ordinary', 'detach'), default='ordinary')
    udp.add_argument('--seconds', type=int, choices=range(1, 121), default=20, metavar='1..120')
    udp.add_argument('--signal', choices=('silence', 'tone'), default='silence')
    udp.add_argument('--wav', help='44.1 kHz stereo 16-bit PCM WAV test input')
    udp.add_argument('--audible', action='store_true', help='Explicitly unmute a tone or WAV test, at most 30 seconds')
    udp.add_argument('--test-volume', type=int, choices=range(36), default=15, metavar='0..35')
    udp.add_argument('--promotion-delay', type=int, choices=range(3, 31), default=8, metavar='3..30')
    args = parser.parse_args(argv)
    helper_path = args.helper_config or os.path.join(os.path.dirname(os.path.abspath(args.config)), 'native-helper.json')
    if not args.command:
        parser.print_help()
        return 2
    if args.command in ('helper-set', 'helper-show'):
        selected = save_helper(helper_path, args.address) if args.command == 'helper-set' else load_helper(helper_path)
        print(json.dumps({'helper': selected, 'config': helper_path,
                          'scope': 'Native AirPlay helper; restart bridge after changes. native_udp selects output.'}, indent=2))
        return 0
    if args.command == 'native-mode':
        set_native_mode(args.config, helper_path, bool(args.enabled), args.muted, args.sync_offset_ms)
        print('Default native AirPlay output ' + ('enabled' if args.enabled else 'disabled') + '; restart the bridge to apply. Device overrides are preserved.')
        return 0
    if args.command == 'udp-test':
        if sys.version_info < (3, 8):
            raise RuntimeError('UDP tests need Python 3.8+ on your test host')
        if args.wav and args.signal != 'silence':
            raise ValueError('Choose WAV or generated tone, not both')
        if args.audible and ((args.signal != 'tone' and not args.wav) or args.seconds > 30):
            raise ValueError('Audible tests require --signal tone or --wav and at most 30 seconds')
        if args.mode == 'detach' and args.seconds < args.promotion_delay + 2:
            raise ValueError('Detached test needs at least two seconds after promotion')
        if not 0 <= args.lock_timeout <= 60:
            raise ValueError('Lock timeout must be 0..60 seconds')
        if bool(args.coordinator) != bool(args.coordinator_id):
            raise ValueError('Specify both helper override address and device ID')
        if not args.coordinator:
            selected = load_helper(helper_path)
            args.coordinator, args.coordinator_id = selected['address'], selected['uuid']
        directory = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                                 'research', 'sonos-native')
        probe = os.path.join(directory, 'group_receiver_probe.py')
        library = os.path.join(directory, 'native', 'build',
                               'libsonos_native.dylib' if sys.platform == 'darwin' else 'libsonos_native.so')
        if not os.path.isfile(probe) or not os.path.isfile(library):
            raise RuntimeError('Use the full Git checkout and first run: make -C research/sonos-native/native')
        command = [sys.executable, probe]
        for name in ('receiver', 'receiver_id', 'coordinator', 'coordinator_id', 'output',
                     'seconds', 'signal', 'test_volume', 'promotion_delay', 'lock_timeout'):
            command.extend(['--' + name.replace('_', '-'), str(getattr(args, name))])
        if args.mode == 'detach':
            command.extend(['--promote-receiver', '--promotion-mode', 'detach'])
        if args.audible:
            command.append('--audible')
        if args.wav:
            command.extend(['--wav', args.wav])
        return subprocess.call(command)
    if args.command == 'clip-test':
        if sys.version_info < (3, 8):
            raise RuntimeError('Clip tests need Python 3.8+; run this command on a Mac or modern Linux host')
        probe = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                             'research', 'sonos-native', 'clip_stream_probe.py')
        if not os.path.isfile(probe):
            raise RuntimeError('Run clip-test from the full Git checkout on your test host')
        command = [sys.executable, probe, '--receiver', args.receiver, '--receiver-id', args.receiver_id,
                   '--output', args.output, '--seconds', str(args.seconds)]
        if args.streaming:
            command.append('--streaming')
        return subprocess.call(command)
    if args.command == 'restart':
        return subprocess.call(['systemctl', 'restart', 'airplay_sonos.service'])
    root = ET.parse(args.config).getroot() if os.path.isfile(args.config) else ET.Element('airupnp')
    api = args.api or root.findtext('sonos_api', '')
    cache = root.findtext('sonos_cache', '')
    if args.command == 'status':
        code = subprocess.call(['systemctl', 'status', '--no-pager', 'airplay_sonos.service'])
        print(json.dumps({'config': args.config, 'room_api': api, 'room_cache': cache,
                          'configured_default_backend': 'native UDP' if root.findtext('common/native_udp', '0') == '1' else 'UPnP HTTP',
                          'configured_native_sync_offset_ms': int(root.findtext('common/native_sync_offset_ms', '0')),
                          'configured_native_muted': root.findtext('common/native_muted', '0') == '1',
                          'helper_config': root.findtext('sonos_native_helper', ''),
                          'device_overrides': [dict([('udn', d.findtext('udn', ''))] + [(key, d.findtext(key)) for key in ('native_udp', 'native_muted', 'native_sync_offset_ms') if d.find(key) is not None]) for d in root.findall('device') if any(d.find(key) is not None for key in ('native_udp', 'native_muted', 'native_sync_offset_ms'))],
                          'note': 'Configuration on disk; restart required after changes.'}, indent=2))
        return code
    print(json.dumps(room_list(api, cache, root.findtext('sonos_name_prefix', ''),
                               root.findtext('sonos_name_suffix', ' (Sonos)')), indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError, ET.ParseError) as exc:
        print('airconnectctl: ' + str(exc), file=sys.stderr)
        sys.exit(1)
