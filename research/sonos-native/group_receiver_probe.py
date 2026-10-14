#!/usr/bin/env python3
"""Bounded silent UDP receiver probe using an ordinary, stopped Sonos coordinator.

No AudioIn/VirtualLineIn actions and no Connect-specific setup. This still uses
another physical speaker for group membership; it is not an independent backend.
Synthetic handoff is bounded research: current live tests lose the receiver after
about 76 seconds when the coordinator is absent from trusted topology.
Requires two stopped standalone speakers and verifies restoration of both.
"""
import argparse
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys
import time
import threading
import xml.etree.ElementTree as ET

from native_sender import NativeSender
from soap import call
from probe import values, AV, RC

def virtual_identity(receiver_id):
    return 'RINCON_02' + hashlib.sha256(receiver_id.encode()).hexdigest()[:10].upper() + '01400'


def group_for(topology, uid):
    return next((g for g in ET.fromstring(topology['ZoneGroupState']).iter('ZoneGroup')
                 if any(m.get('UUID') == uid for m in g.iter('ZoneGroupMember'))), None)


def standalone(snapshot, uid):
    group = group_for(snapshot['topology'], uid)
    return group is not None and group.get('Coordinator') == uid and len(list(group.iter('ZoneGroupMember'))) == 1


def run(args):
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {'actions': [], 'restore_errors': [], 'phases': [],
              'audio_in_calls': 0, 'virtual_line_in_calls': 0,
              'silent': True, 'independent_setup': False}
    virtual_id = virtual_identity(args.receiver_id)
    result['virtual_id'] = virtual_id
    result['started_utc'] = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    def save():
        output.write_text(json.dumps(result, indent=2) + '\n')
    def action(ip, name, arguments, path=AV, service='AVTransport'):
        response = call(ip, path, service, name, arguments)
        result['actions'].append({'at': round(time.monotonic()-started, 4), 'ip': ip,
                                  'action': name, 'arguments': arguments, 'response': response})
        save()
        return values(response)
    def av(ip, name, **kw): return action(ip, name, {'InstanceID': 0, **kw})
    def rc(ip, name, **kw): return action(ip, name, {'InstanceID': 0, 'Channel': 'Master', **kw}, RC, 'RenderingControl')
    def snapshot(ip):
        return {'media': av(ip, 'GetMediaInfo'), 'transport': av(ip, 'GetTransportInfo'),
                'mute': rc(ip, 'GetMute'), 'volume': rc(ip, 'GetVolume'),
                'topology': action(ip, 'GetZoneGroupState', {}, '/ZoneGroupTopology/Control', 'ZoneGroupTopology')}
    devices = [(args.receiver, args.receiver_id), (args.coordinator, args.coordinator_id)]
    if args.receiver == args.coordinator or args.receiver_id == args.coordinator_id:
        raise ValueError('Use two different speakers')
    before = {ip: snapshot(ip) for ip, _ in devices}
    result['before'] = before
    save()
    for ip, uid in devices:
        if not standalone(before[ip], uid) or before[ip]['transport']['CurrentTransportState'] != 'STOPPED':
            raise RuntimeError('Both speakers must be stopped and standalone; no mutation')
        group = group_for(before[ip]['topology'], uid)
        member = next(group.iter('ZoneGroupMember'))
        if not member.get('Location', '').startswith('http://' + ip + ':'):
            raise RuntimeError('Device address/UUID mismatch; no mutation')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
        route.connect((args.receiver, 7020))
        local = route.getsockname()[0]
    library = str(Path(__file__).parent / 'native' / 'build' /
                  ('libsonos_native.dylib' if sys.platform == 'darwin' else 'libsonos_native.so'))
    # Validate library before changing a speaker.
    sender = NativeSender(library, local, args.receiver)
    sender.close()
    changed = False
    try:
        changed = True
        for ip, _ in devices: rc(ip, 'SetMute', DesiredMute=1)
        av(args.receiver, 'SetAVTransportURI', CurrentURI='x-rincon:' + args.coordinator_id, CurrentURIMetaData='')
        joined = snapshot(args.receiver)
        result['joined'] = joined
        group = group_for(joined['topology'], args.receiver_id)
        if group is None or group.get('Coordinator') != args.coordinator_id:
            raise RuntimeError('Receiver did not join the intended coordinator')
        phases = ['ordinary-group'] + (['synthetic-coordinator'] if args.handoff_to_synthetic else [])
        for phase_name in phases:
            sender = NativeSender(library, local, args.receiver)
            phase = {'name': phase_name}
            worker = None
            stop = threading.Event()
            ready = threading.Event()
            errors = []
            result['phases'].append(phase)
            try:
                source = args.coordinator_id if phase_name == 'ordinary-group' else virtual_id
                settings = '234.142.199.198:7020,{}:7000:7010:{},{}'.format(local, sender.clock_port, source)
                uri = 'x-rincon:' + source
                if phase_name == 'ordinary-group':
                    av(args.receiver, 'ChangeTransportSettings', NewTransportSettings=settings, CurrentAVTransportURI=uri)
                else:
                    av(args.receiver, 'ChangeCoordinator', CurrentCoordinator=args.coordinator_id,
                       NewCoordinator=virtual_id, NewTransportSettings=settings,
                       CurrentAVTransportURI=uri, RestartSink=1)
                phase['setup_accepted'] = True
                duration = min(args.seconds, 3) if phase_name == 'ordinary-group' and args.handoff_to_synthetic else args.seconds
                phase['duration_seconds'] = duration
                phase['clock_port'] = sender.clock_port
                def produce():
                    try:
                        for _ in range(int(duration * 44100 / 251)):
                            if stop.is_set(): break
                            sender.write(bytes(1004))
                            ready.set()
                    except Exception as exc:
                        errors.append(str(exc))
                        ready.set()
                worker = threading.Thread(target=produce)
                worker.start()
                if not ready.wait(3): raise RuntimeError('Sender did not start')
                if phase_name == 'synthetic-coordinator' and args.release_coordinator:
                    action(args.coordinator, 'RemoveMember', {'MemberID': args.receiver_id}, '/GroupManagement/Control', 'GroupManagement')
                    phase['remove_member_accepted'] = True
                    if args.reset_helper_group:
                        phase['helper_standalone_response'] = av(args.coordinator, 'BecomeCoordinatorOfStandaloneGroup')
                save()
                phase_start = time.monotonic()
                phase['progress'] = []
                while worker.is_alive() and time.monotonic() - phase_start < duration + 5:
                    worker.join(1)
                    phase['progress'].append({'elapsed': round(time.monotonic() - phase_start, 3), **sender.stats()})
                    save()
                if worker.is_alive(): raise RuntimeError('Sender exceeded bounded duration')
                if errors: raise RuntimeError(errors[0])
                phase['media'] = av(args.receiver, 'GetMediaInfo')
                phase['coordinator_state'] = snapshot(args.coordinator)
                phase['state'] = av(args.receiver, 'GetTransportInfo')
                phase['topology'] = action(args.receiver, 'GetZoneGroupState', {}, '/ZoneGroupTopology/Control', 'ZoneGroupTopology')
                phase['helper_standalone'] = standalone(phase['coordinator_state'], args.coordinator_id)
                receiver_group = group_for(phase['topology'], args.receiver_id)
                phase['receiver_group_coordinator'] = receiver_group.get('Coordinator') if receiver_group is not None else None
            except Exception as exc:
                phase['error'] = str(exc)
                try:
                    phase['failure_snapshot'] = snapshot(args.receiver)
                except Exception as state_error:
                    phase['failure_snapshot_error'] = str(state_error)
                raise
            finally:
                stop.set()
                if worker: worker.join()
                phase['stats'] = sender.stats()
                sender.close()
                phase['transport_check_passed'] = (phase.get('setup_accepted', False) and not phase.get('error') and
                    phase['stats']['clock_requests'] > 0 and
                    phase['stats']['packets'] == int(phase.get('duration_seconds', 0) * 44100 / 251) and
                    phase.get('state', {}).get('CurrentTransportState') == 'PLAYING')
                save()
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        if changed:
            # Break the temporary group before restoring either source. Keep both
            # muted until all source/state restoration attempts have completed.
            operations = [('receiver standalone', lambda: av(args.receiver, 'BecomeCoordinatorOfStandaloneGroup'))]
            for ip, _ in devices:
                operations += [(ip + ' source', lambda ip=ip: av(ip, 'SetAVTransportURI',
                    CurrentURI=before[ip]['media']['CurrentURI'], CurrentURIMetaData=before[ip]['media']['CurrentURIMetaData'])),
                    (ip + ' stopped', lambda ip=ip: av(ip, 'Stop'))]
            for ip, _ in devices:
                operations.append((ip + ' volume', lambda ip=ip: rc(ip, 'SetVolume', DesiredVolume=before[ip]['volume']['CurrentVolume'])))
            for ip, _ in devices:
                operations.append((ip + ' mute', lambda ip=ip: rc(ip, 'SetMute', DesiredMute=before[ip]['mute']['CurrentMute'])))
            for label, operation in operations:
                try: operation()
                except Exception as exc: result['restore_errors'].append({'step': label, 'error': str(exc)})
            result['verified'] = {}
            for ip, uid in devices:
                try:
                    after = snapshot(ip)
                    result.setdefault('after', {})[ip] = after
                    checks = {k: after[k] == before[ip][k] for k in ('transport', 'mute', 'volume')}
                    checks['source'] = all(after['media'].get(k) == before[ip]['media'].get(k) for k in ('CurrentURI', 'CurrentURIMetaData'))
                    checks['standalone'] = standalone(after, uid)
                    result['verified'][ip] = checks
                except Exception as exc: result['restore_errors'].append({'step': ip + ' verification', 'error': str(exc)})
        save()
    summary = {k: result[k] for k in ('error', 'verified', 'restore_errors') if k in result}
    summary['phases'] = [{k: p[k] for k in ('name', 'setup_accepted', 'stats', 'state', 'error', 'transport_check_passed', 'helper_standalone', 'receiver_group_coordinator') if k in p} for p in result['phases']]
    print(json.dumps(summary, indent=2))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('receiver', 'receiver-id', 'coordinator', 'coordinator-id', 'output'):
        p.add_argument('--' + arg, required=True)
    p.add_argument('--seconds', type=int, choices=range(1, 121), default=3)
    p.add_argument('--handoff-to-synthetic', action='store_true', help='After group setup, test ChangeCoordinator to a synthetic identity')
    p.add_argument('--release-coordinator', action='store_true', help='After handoff, remove receiver from the real coordinator membership list')
    p.add_argument('--reset-helper-group', action='store_true', help='After RemoveMember, request standalone state on the helper to test group independence')
    args = p.parse_args()
    if args.release_coordinator and not args.handoff_to_synthetic: p.error('--release-coordinator requires --handoff-to-synthetic')
    if args.reset_helper_group and not args.release_coordinator: p.error('--reset-helper-group requires --release-coordinator')
    result = run(args)
    if not result['phases'] or not all(p.get('transport_check_passed') for p in result['phases']) or result.get('error') or result['restore_errors'] or not all(all(v.values()) for v in result.get('verified', {}).values()):
        raise SystemExit(1)

if __name__ == '__main__': main()
