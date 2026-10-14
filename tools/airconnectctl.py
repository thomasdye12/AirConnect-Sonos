#!/usr/bin/env python3
"""Local bridge management. Python 3.4+; experimental transport tests need Python 3.8+."""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

LIMIT = 1024 * 1024


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
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('status', help='Local systemd status and configuration (read only)')
    sub.add_parser('rooms', help='Validated API coordinator names, with cache fallback')
    sub.add_parser('restart', help='Restart the local bridge and refresh its startup room list')
    clip = sub.add_parser('clip-test', help='Experimental bounded SILENT HTTP WAV test, not AirPlay')
    clip.add_argument('--receiver', required=True)
    clip.add_argument('--receiver-id', required=True)
    clip.add_argument('--output', required=True, help='Private JSON result file')
    clip.add_argument('--seconds', type=int, choices=range(1, 61), default=12, metavar='1..60')
    clip.add_argument('--streaming', action='store_true')
    udp = sub.add_parser('udp-test', help='Experimental bounded UDP test with a stopped helper; muted by default')
    for name in ('receiver', 'receiver-id', 'coordinator', 'coordinator-id', 'output'):
        udp.add_argument('--' + name, required=True)
    udp.add_argument('--mode', choices=('ordinary', 'detach'), default='ordinary')
    udp.add_argument('--seconds', type=int, choices=range(1, 121), default=20, metavar='1..120')
    udp.add_argument('--signal', choices=('silence', 'tone'), default='silence')
    udp.add_argument('--audible', action='store_true', help='Explicitly unmute a tone test, at most 30 seconds')
    udp.add_argument('--test-volume', type=int, choices=range(36), default=15, metavar='0..35')
    udp.add_argument('--promotion-delay', type=int, choices=range(3, 31), default=8, metavar='3..30')
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    if args.command == 'udp-test':
        if sys.version_info < (3, 8):
            raise RuntimeError('UDP tests need Python 3.8+ on your test host')
        if args.audible and (args.signal != 'tone' or args.seconds > 30):
            raise ValueError('Audible tests require --signal tone and at most 30 seconds')
        if args.mode == 'detach' and args.seconds < args.promotion_delay + 2:
            raise ValueError('Detached test needs at least two seconds after promotion')
        directory = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                                 'research', 'sonos-native')
        probe = os.path.join(directory, 'group_receiver_probe.py')
        library = os.path.join(directory, 'native', 'build',
                               'libsonos_native.dylib' if sys.platform == 'darwin' else 'libsonos_native.so')
        if not os.path.isfile(probe) or not os.path.isfile(library):
            raise RuntimeError('Use the full Git checkout and first run: make -C research/sonos-native/native')
        command = [sys.executable, probe]
        for name in ('receiver', 'receiver_id', 'coordinator', 'coordinator_id', 'output',
                     'seconds', 'signal', 'test_volume', 'promotion_delay'):
            command.extend(['--' + name.replace('_', '-'), str(getattr(args, name))])
        if args.mode == 'detach':
            command.extend(['--promote-receiver', '--promotion-mode', 'detach'])
        if args.audible:
            command.append('--audible')
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
                          'playback_backend': 'UPnP HTTP (production)',
                          'native_udp_backend': 'research only; independent setup unresolved'}, indent=2))
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
