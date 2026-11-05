#!/usr/bin/env python3
"""Install/start the already generated room manifest on the standard Linux host.

Requires root and Python 3.4+. Default is a read-only plan. With --apply, replaces
only this integration's template and target, stopping removed room units first.
Requires the matched frontend/worker, 32-client NQPTP and generated configs to
have been installed and tested separately. Apply during a maintenance window:
restarting room services disconnects streams and invokes worker restoration.
"""
import argparse
import json
import os
import re
import subprocess

BASE = '/srv/airconnect-airplay2'
UNIT_DIR = '/etc/systemd/system'


def units(manifest):
    if manifest.get('version') != 1 or not manifest.get('rooms'):
        raise ValueError('Missing versioned room manifest')
    if len(manifest['rooms']) > manifest.get('timing_capacity', 0):
        raise ValueError('Timing capacity exceeded')
    result = []
    for room in manifest['rooms']:
        key = room['key']
        if not re.fullmatch('[0-9a-f]{17}', key):
            raise ValueError('Invalid room unit identity')
        result.append('airconnect-ap2@' + key + '.service')
    if len(result) != len(set(result)):
        raise ValueError('Duplicate room unit')
    return result


def run(*args):
    subprocess.check_call(['systemctl'] + list(args))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--enable', action='store_true', help='Start rooms automatically at boot')
    a = p.parse_args()
    with open(BASE + '/rooms/manifest.json') as f:
        manifest = json.load(f)
    desired = units(manifest)
    with open(os.path.join(os.path.dirname(__file__), 'airconnect-ap2@.service')) as f:
        template = f.read()
    for room in manifest['rooms']:
        if not os.path.isfile(BASE + '/rooms/' + room['key'] + '.conf'):
            raise ValueError('Missing generated room config')
    print('\n'.join(desired))
    if not a.apply:
        return
    if os.geteuid() != 0:
        p.error('--apply requires root')
    old = []
    state = BASE + '/rooms/installed-units.json'
    if os.path.exists(state):
        with open(state) as f:
            old = json.load(f)
        if any(not re.fullmatch(r'airconnect-ap2@[0-9a-f]{17}\.service', name) for name in old):
            raise ValueError('Invalid installed unit record')
    for unit in sorted(set(old) - set(desired)):
        run('stop', unit)
    with open(UNIT_DIR + '/airconnect-ap2@.service', 'w') as f:
        f.write(template)
    target = '[Unit]\nDescription=AirConnect AirPlay 2 rooms\nWants=' + ' '.join(desired) + '\nAfter=network-online.target\n\n[Install]\nWantedBy=multi-user.target\n'
    with open(UNIT_DIR + '/airconnect-ap2-rooms.target', 'w') as f:
        f.write(target)
    run('daemon-reload')
    # Restart loads changed configurations for existing rooms as well as new ones.
    for unit in desired:
        run('restart', unit)
    run('start', 'airconnect-ap2-rooms.target')
    if a.enable:
        run('enable', 'airconnect-ap2-rooms.target')
    with open(state, 'w') as f:
        json.dump(desired, f, indent=2)


if __name__ == '__main__':
    main()
