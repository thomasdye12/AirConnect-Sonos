#!/usr/bin/env python3
"""Read-only AirConnect dashboard. Standard library only; Python 3.4+."""
import argparse
import binascii
import copy
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

LIMIT = 1024 * 1024
SERVICE = 'airplay_sonos.service'
UID = re.compile(r'^RINCON_[0-9A-F]{17}$')


def read_json(stream):
    raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('JSON exceeds 1 MiB')
    return json.loads(raw.decode('utf-8'))


def read_config(path):
    with open(path, 'rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Configuration exceeds 1 MiB')
    root = ET.fromstring(raw)
    if root.tag != 'airupnp':
        raise ValueError('Expected AirUPnP configuration')
    defaults = {'native_udp': '0', 'native_muted': '0',
                'native_sync_offset_ms': '0', 'latency': '1000:2000'}
    common = root.find('common')
    for key in defaults:
        if common is not None:
            defaults[key] = common.findtext(key, defaults[key])
    overrides = {}
    for device in root.findall('device'):
        uid = device.findtext('udn', '').replace('uuid:', '', 1)
        if UID.match(uid):
            overrides[uid] = {k: device.findtext(k) for k in defaults if device.find(k) is not None}
    return {'defaults': defaults, 'overrides': overrides,
            'api': root.findtext('sonos_api', ''),
            'cache': root.findtext('sonos_cache', ''),
            'helper_path': root.findtext('sonos_native_helper', os.path.join(os.path.dirname(path), 'native-helper.json')),
            'prefix': root.findtext('sonos_name_prefix', ''),
            'suffix': root.findtext('sonos_name_suffix', ' (Sonos)'),
            'modified_at': os.stat(path).st_mtime}


def system_status():
    keys = ['ActiveState', 'SubState', 'MainPID', 'ExecMainStartTimestamp', 'ExecMainStartTimestampMonotonic']
    try:
        command = ['systemctl', 'show', SERVICE]
        for key in keys:
            command.extend(['-p', key])
        output = subprocess.check_output(command, stderr=subprocess.STDOUT, timeout=3).decode('utf-8', 'replace')
        state = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
        state['pid'] = int(state.get('MainPID', '0'))
        state['running'] = state.get('ActiveState') == 'active' and state.get('SubState') == 'running'
        start = int(state.get('ExecMainStartTimestampMonotonic', '0')) / 1000000.0
        state['uptime_seconds'] = max(0, int(time.monotonic() - start)) if state['running'] and start else None
        return state
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {'running': False, 'pid': 0, 'ActiveState': 'unknown', 'error': str(exc)}


def held_devices(pid, proc='/proc'):
    """Observe the bridge's existing flock leases without acquiring any lock.

    A held lease means setup/session/restore ownership, not audible playback.
    Matching both PID and inode prevents stale lock files from appearing active.
    """
    if not pid:
        return []
    locked = set()
    with open(os.path.join(proc, 'locks')) as stream:
        for line in stream:
            fields = line.split()
            if len(fields) >= 6 and fields[1:4] == ['FLOCK', 'ADVISORY', 'WRITE'] and fields[4] == str(pid):
                major, minor, inode = fields[5].split(':')
                locked.add((int(major, 16), int(minor, 16), int(inode)))
    result = set()
    fd_dir = os.path.join(proc, str(pid), 'fd')
    for fd in os.listdir(fd_dir):
        try:
            path = os.path.join(fd_dir, fd)
            target = os.readlink(path)
            if '/airconnect-native-' not in target or not target.endswith('.lock'):
                continue
            stat = os.stat(path)
            if (os.major(stat.st_dev), os.minor(stat.st_dev), stat.st_ino) not in locked:
                continue
            uid = binascii.unhexlify(os.path.basename(target)[:-5]).decode('ascii')
            if UID.match(uid):
                result.add(uid)
        except (OSError, ValueError, UnicodeError, binascii.Error):
            continue
    return sorted(result)


def parse_log(raw):
    # A startup marker resets historical sessions and pointer identities.
    lines = raw.splitlines()
    starts = [i for i, line in enumerate(lines) if 'Starting airupnp version:' in line]
    complete = bool(starts)
    if starts:
        lines = lines[starts[-1]:]
    result = {'version': None, 'has_start_marker': complete, 'addresses': {},
              'sessions': {}, 'completed': [], 'timing': [], 'events': []}
    event_pattern = re.compile(r'native |PCM output failed|Starting airupnp|error|failed|refused|discontinuity', re.I)
    for line in lines:
        stamp = line[1:13] if line.startswith('[') else ''
        match = re.search(r'Starting airupnp version:\s*(\S+)', line)
        if match:
            result['version'] = match.group(1)
        match = re.search(r'adding renderer \((\d+\.\d+\.\d+\.\d+) - .*? - (RINCON_[0-9A-F]{17})\)', line)
        if match:
            result['addresses'][match.group(2)] = match.group(1)
        match = re.search(r'native PCM started for ([0-9.]+)', line)
        if match:
            result['sessions'][match.group(1)] = {'phase': 'Helper setup', 'log_time': stamp}
        match = re.search(r'native helper released; independent PCM continues for ([0-9.]+)', line)
        if match:
            result['sessions'][match.group(1)] = {'phase': 'Independent UDP session', 'log_time': stamp}
        match = re.search(r'native sender ([0-9.]+) (packets=.*)', line)
        if match:
            stats = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', match.group(2))}
            stats.update({'address': match.group(1), 'log_time': stamp})
            result['completed'].append(stats)
            result['sessions'].pop(match.group(1), None)
        if 'native PCM timing samples=' in line:
            stats = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', line)}
            stats['log_time'] = stamp
            result['timing'].append(stats)
        if event_pattern.search(line):
            warning = bool(re.search(r'error|failed|refused|discontinuity|skipped .* expired', line, re.I))
            result['events'].append({'time': stamp, 'level': 'warning' if warning else 'info', 'text': line[:1200]})
    for key, count in [('completed', 12), ('timing', 12), ('events', 100)]:
        result[key] = result[key][-count:][::-1]
    return result


class LogReader:
    def __init__(self, path):
        self.path, self.signature, self.value = path, None, None

    def read(self):
        stat = os.stat(self.path)
        signature = (stat.st_ino, stat.st_size, stat.st_mtime)
        if signature != self.signature:
            with open(self.path, 'rb') as stream:
                offset = max(0, stat.st_size - 2 * LIMIT)
                stream.seek(offset)
                raw = stream.read(2 * LIMIT)
            if offset:
                raw = raw.partition(b'\n')[2]
            self.value = parse_log(raw.decode('utf-8', 'replace'))
            self.value['modified_at'] = stat.st_mtime
            self.value['tail_limited'] = bool(offset)
            self.signature = signature
        return copy.deepcopy(self.value)


def normalize_zones(zones):
    if not isinstance(zones, list) or not 1 <= len(zones) <= 128:
        raise ValueError('Invalid zones response')
    rooms, seen = [], set()
    for zone in zones:
        coordinator = zone['coordinator']
        cid = coordinator['uuid']
        members = zone.get('members') or [coordinator]
        if not UID.match(cid) or len(members) > 128:
            raise ValueError('Invalid coordinator')
        for member in members:
            uid, name = member['uuid'], member['roomName']
            if not UID.match(uid) or not isinstance(name, str) or not name or uid in seen:
                raise ValueError('Invalid or duplicate room')
            seen.add(uid)
            state = member.get('state') or {}
            track = state.get('currentTrack') or {}
            rooms.append({'uuid': uid, 'name': name[:200], 'coordinator': cid,
                          'group_name': coordinator['roomName'][:200], 'group_size': len(members),
                          'sonos_state': state.get('playbackState', 'Unknown'),
                          'volume': state.get('volume'), 'muted': state.get('mute'),
                          'track': {k: str(track.get(k, ''))[:500] for k in ('title', 'artist', 'album')}})
    return sorted(rooms, key=lambda item: item['name'].lower())


class Collector:
    def __init__(self, config, log):
        self.config_path, self.log = config, LogReader(log)
        self.lock = threading.Lock()
        self.snapshot = {'ready': False, 'collected_at': time.time()}
        self.rooms, self.rooms_at, self.rooms_api, self.rooms_attempt = [], 0, '', 0
        self.rooms_error = None

    def room_snapshot(self, config):
        now = time.time()
        api = config['api']
        if api != self.rooms_api:
            self.rooms, self.rooms_at, self.rooms_attempt = [], 0, 0
            self.rooms_api = api
        if now - self.rooms_attempt >= 15:
            self.rooms_attempt = now
            try:
                if not api.startswith('http://'):
                    raise ValueError('No local HTTP room API configured')
                with urllib.request.urlopen(api, timeout=3) as stream:
                    self.rooms = normalize_zones(read_json(stream))
                self.rooms_at, self.rooms_error = time.time(), None
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                self.rooms_error = str(exc)
                if not self.rooms and config['cache']:
                    try:
                        with open(config['cache'], 'rb') as stream:
                            cached = read_json(stream)
                        age = now - cached['fetched_at']
                        if cached.get('version') != 1 or cached.get('api') != api or not 0 <= age <= 86400:
                            raise ValueError('Room cache is expired or for another API')
                        self.rooms = normalize_zones(cached['zones'])
                        self.rooms_at = cached['fetched_at']
                    except (OSError, ValueError, KeyError, TypeError, AttributeError):
                        pass
        return copy.deepcopy(self.rooms), {'url': api, 'fetched_at': self.rooms_at or None,
                                         'stale': bool(self.rooms_error), 'error': self.rooms_error}

    def collect(self):
        errors = []
        service = system_status()
        config = read_config(self.config_path)
        try:
            with open(config['helper_path'], 'rb') as stream:
                helper = read_json(stream)['helper']
            helper = {key: str(helper.get(key, ''))[:200] for key in ('name', 'uuid', 'address')}
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            helper = {}
            errors.append('Helper configuration unavailable: ' + str(exc))
        try:
            logs = self.log.read()
        except (OSError, ValueError) as exc:
            logs = parse_log('')
            errors.append('Log unavailable: ' + str(exc))
        try:
            leases = held_devices(service['pid']) if service['running'] else []
            ownership_known = 'error' not in service
        except OSError as exc:
            leases, ownership_known = [], False
            errors.append('Native ownership unavailable: ' + str(exc))
        # Recheck PID so a restart during collection cannot leave old leases active.
        check = system_status()
        if check.get('pid') != service.get('pid') or check.get('running') != service.get('running'):
            service, leases, ownership_known = check, [], False
        intercom = {'available': False, 'sessions': [], 'recent': []}
        try:
            with open('/run/airconnect-intercom/status.json', 'rb') as stream:
                intercom = read_json(stream)
            intercom['available'] = True
            intercom['stale'] = time.time() - intercom.get('updated_at', 0) > 15
            if not intercom['stale']:
                for session in intercom.get('sessions', []):
                    try:
                        leases = sorted(set(leases + held_devices(session.get('worker_pid'))))
                    except OSError:
                        pass
        except (OSError, ValueError):
            pass
        rooms, api = self.room_snapshot(config)
        for room in rooms:
            settings = dict(config['defaults'])
            settings.update(config['overrides'].get(room['uuid'], {}))
            room['settings'] = settings
            room['is_helper'] = room['uuid'] == helper.get('uuid')
            room['address'] = logs['addresses'].get(room['uuid'])
            room['airplay_name'] = config['prefix'] + room['name'] + config['suffix']
            room['session_held'] = room['uuid'] in leases if ownership_known else None
            room['phase'] = None
            if room['session_held']:
                room['phase'] = logs['sessions'].get(room['address'], {}).get('phase', 'Setup / session / restore')
                for session in intercom.get('sessions', []):
                    if session.get('uuid') == room['uuid'] and not intercom.get('stale', True):
                        room['phase'] = 'Intercom · ' + session.get('state', 'unknown')
        # Preserve held devices missing from an old API/cache snapshot.
        known = {r['uuid'] for r in rooms}
        unknown = [uid for uid in leases if uid not in known and uid != helper.get('uuid')]
        by_ip = {r['address']: r['name'] for r in rooms if r['address']}
        for record in logs['completed']:
            record['room'] = by_ip.get(record['address'], record['address'])
        helper['held'] = helper.get('uuid') in leases if ownership_known else None
        count = len([uid for uid in leases if uid != helper.get('uuid')]) if ownership_known else None
        return {'ready': True, 'collected_at': time.time(), 'service': service, 'config': config,
                'helper': helper, 'rooms': rooms, 'api': api, 'logs': logs, 'errors': errors, 'intercom': intercom,
                'native_sessions': count, 'unknown_sessions': unknown,
                'host': {'hostname': socket.gethostname(), 'load': list(os.getloadavg())}}

    def refresh(self):
        try:
            result = self.collect()
        except Exception as exc:
            # Retain the timestamp of the last good snapshot, visibly mark failure.
            with self.lock:
                result = copy.deepcopy(self.snapshot)
            result['collector_error'] = str(exc)
        with self.lock:
            self.snapshot = result

    def run(self):
        while True:
            self.refresh()
            time.sleep(5)

    def read(self):
        with self.lock:
            return copy.deepcopy(self.snapshot)


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler):
        self.slots = threading.BoundedSemaphore(12)
        HTTPServer.__init__(self, address, handler)

    def process_request(self, request, address):
        request.settimeout(5)
        if not self.slots.acquire(False):
            self.shutdown_request(request)
            return
        try:
            ThreadingMixIn.process_request(self, request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            ThreadingMixIn.process_request_thread(self, request, address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = 'AirConnectDashboard/1'
    sys_version = ''

    def do_GET(self):
        try:
            host = urllib.parse.urlsplit('//' + self.headers.get('Host', '')).hostname
        except ValueError:
            self.send_error(400, 'Invalid Host header')
            return
        if host not in self.server.allowed_hosts:
            self.send_error(403, 'Use the configured bridge address')
            return
        path = urllib.parse.urlsplit(self.path).path
        routes = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if path in ('/api/status', '/api/diagnostics'):
            body = json.dumps(self.server.collector.read(), ensure_ascii=True).encode('utf-8')
            content_type = 'application/json; charset=utf-8'
        elif path in routes:
            filename, content_type = routes[path]
            with open(os.path.join(self.server.assets, filename), 'rb') as stream:
                body = stream.read()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        if path == '/api/diagnostics':
            self.send_header('Content-Disposition', 'attachment; filename="airconnect-diagnostics.json"')
        self.end_headers()
        try:
            # Python 3.4's unbuffered SocketIO.write may send only part of a
            # large snapshot. Flush headers, then explicitly send the full body.
            self.wfile.flush()
            self.connection.sendall(body)
        except (OSError, socket.timeout):
            pass

    def log_message(self, fmt, *args):
        # Avoid a journal write every five seconds for each open browser.
        if len(args) > 1 and str(args[1]) != '200':
            BaseHTTPRequestHandler.log_message(self, fmt, *args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', default=8088, type=int)
    parser.add_argument('--config', default='/var/airplay_sonos/Config.xml')
    parser.add_argument('--log', default='/var/log/airupnp.log')
    parser.add_argument('--assets', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dashboard'))
    parser.add_argument('--allow-host', action='append', default=[], help='Additional permitted HTTP Host name')
    args = parser.parse_args()
    server = Server((args.bind, args.port), Handler)
    server.allowed_hosts = set([args.bind, 'localhost', '127.0.0.1'] + args.allow_host)
    server.assets = args.assets
    server.collector = Collector(args.config, args.log)
    worker = threading.Thread(target=server.collector.run)
    worker.daemon = True
    worker.start()
    print('Read-only AirConnect dashboard on {}:{}'.format(args.bind, args.port), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
