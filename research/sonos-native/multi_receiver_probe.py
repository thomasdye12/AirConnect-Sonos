#!/usr/bin/env python3
"""Silent two-receiver UDP test with one retained, stopped Sonos coordinator.

This is a research control, not a software-coordinator solution or AirPlay backend.
One owner snapshots/restores all three speakers; never run overlapping probes.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys
import threading
import time

from group_receiver_probe import group_for, standalone
from native_sender import NativeSender
from probe import AV, RC, values
from soap import call


def run(args):
    targets = [(args.first, args.first_id), (args.second, args.second_id)]
    devices = targets + [(args.coordinator, args.coordinator_id)]
    if len({ip for ip, _ in devices}) != 3 or len({uid for _, uid in devices}) != 3:
        raise ValueError('Three distinct speakers are required')
    if not 5 <= args.first_stop <= args.seconds - 5 or not 10 <= args.seconds <= 180:
        raise ValueError('Use 10..180 seconds and stop the first at least five seconds before the end')
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = dict(started_utc=datetime.now(timezone.utc).isoformat(), silent=True,
                  independent_setup=False, actions=[], restore_errors=[], streams={}, progress=[])
    origin = time.monotonic()
    def save(): output.write_text(json.dumps(result, indent=2) + '\n')
    def action(ip, name, arguments, path=AV, service='AVTransport'):
        response = call(ip, path, service, name, arguments)
        result['actions'].append(dict(at=round(time.monotonic()-origin, 4), ip=ip,
                                      action=name, arguments=arguments, response=response))
        save()
        return values(response)
    def av(ip, name, **kw): return action(ip, name, dict(InstanceID=0, **kw))
    def rc(ip, name, **kw): return action(ip, name, dict(InstanceID=0, Channel='Master', **kw), RC, 'RenderingControl')
    def snapshot(ip):
        return dict(media=av(ip, 'GetMediaInfo'), transport=av(ip, 'GetTransportInfo'),
                    mute=rc(ip, 'GetMute'), volume=rc(ip, 'GetVolume'),
                    topology=action(ip, 'GetZoneGroupState', {}, '/ZoneGroupTopology/Control', 'ZoneGroupTopology'))
    before = {ip: snapshot(ip) for ip, _ in devices}
    result['before'] = before
    save()
    for ip, uid in devices:
        if not standalone(before[ip], uid) or before[ip]['transport']['CurrentTransportState'] != 'STOPPED':
            raise RuntimeError('All three speakers must be stopped and standalone; no mutation')
        member = next(group_for(before[ip]['topology'], uid).iter('ZoneGroupMember'))
        if not member.get('Location', '').startswith('http://' + ip + ':'):
            raise RuntimeError('Address/identity mismatch; no mutation')
    library = str(Path(__file__).parent / 'native' / 'build' /
                  ('libsonos_native.dylib' if sys.platform == 'darwin' else 'libsonos_native.so'))
    senders, locals_, workers, worker_errors = {}, {}, {}, {}
    stop = threading.Event()
    changed = False
    try:
        # Allocate every sender before mutating any speaker.
        for ip, _ in targets:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
                route.connect((ip, 7020))
                locals_[ip] = route.getsockname()[0]
            senders[ip] = NativeSender(library, locals_[ip], ip)
            result['streams'][ip] = dict(clock_port=senders[ip].clock_port)
        if len({s.clock_port for s in senders.values()}) != 2:
            raise RuntimeError('Timing port collision')
        changed = True
        for ip, _ in devices: rc(ip, 'SetMute', DesiredMute=1)
        # Complete ordinary membership before either software sink starts.
        for ip, _ in targets:
            av(ip, 'SetAVTransportURI', CurrentURI='x-rincon:' + args.coordinator_id, CurrentURIMetaData='')
        for ip, uid in targets:
            joined = snapshot(ip)
            g = group_for(joined['topology'], uid)
            if g is None or g.get('Coordinator') != args.coordinator_id:
                raise RuntimeError('Receiver did not join intended group')
            settings = '234.142.199.198:7020,{}:7000:7010:{},{}'.format(locals_[ip], senders[ip].clock_port, args.coordinator_id)
            av(ip, 'ChangeTransportSettings', NewTransportSettings=settings,
               CurrentAVTransportURI='x-rincon:' + args.coordinator_id)
            duration = args.first_stop if ip == args.first else args.seconds
            result['streams'][ip]['requested_seconds'] = duration
            def produce(ip=ip, duration=duration):
                try:
                    for _ in range(int(duration * 44100 / 251)):
                        if stop.is_set(): break
                        senders[ip].write(bytes(1004))
                except Exception as exc:
                    worker_errors[ip] = str(exc)
            workers[ip] = threading.Thread(target=produce)
            workers[ip].start()
        started = time.monotonic()
        first_stopped = False
        while any(w.is_alive() for w in workers.values()):
            stop.wait(1)
            if worker_errors: raise RuntimeError(str(worker_errors))
            elapsed = time.monotonic() - started
            result['progress'].append(dict(elapsed=round(elapsed, 3), streams={ip:s.stats() for ip,s in senders.items()}))
            if elapsed >= 3 and 'overlap' not in result:
                result['overlap'] = {ip: snapshot(ip) for ip, _ in devices}
            if not workers[args.first].is_alive() and not first_stopped:
                result['first_before_stop'] = snapshot(args.first)
                # Detach just this receiver. Do not change the shared helper.
                av(args.first, 'BecomeCoordinatorOfStandaloneGroup')
                av(args.first, 'SetAVTransportURI', CurrentURI=before[args.first]['media']['CurrentURI'],
                   CurrentURIMetaData=before[args.first]['media']['CurrentURIMetaData'])
                av(args.first, 'Stop')
                result['after_first_stop'] = {ip: snapshot(ip) for ip, _ in devices}
                result['second_packets_at_first_stop'] = senders[args.second].stats()['packets']
                first_stopped = True
            save()
            if elapsed > args.seconds + 10: raise RuntimeError('Bounded duration exceeded')
        if worker_errors: raise RuntimeError(str(worker_errors))
        result['end'] = {ip: snapshot(ip) for ip, _ in devices}
        result['checks'] = dict(
            both_playing_in_overlap=all(result.get('overlap', {}).get(ip, {}).get('transport', {}).get('CurrentTransportState') == 'PLAYING' for ip,_ in targets),
            first_playing_before_stop=result.get('first_before_stop', {}).get('transport', {}).get('CurrentTransportState') == 'PLAYING',
            first_stopped=result['end'][args.first]['transport']['CurrentTransportState'] == 'STOPPED',
            second_playing_after_first_stop=result.get('after_first_stop', {}).get(args.second, {}).get('transport', {}).get('CurrentTransportState') == 'PLAYING',
            second_playing_at_end=result['end'][args.second]['transport']['CurrentTransportState'] == 'PLAYING',
            helper_stopped=result['end'][args.coordinator]['transport']['CurrentTransportState'] == 'STOPPED',
            second_packets_continue=senders[args.second].stats()['packets'] > result.get('second_packets_at_first_stop', float('inf')))
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        stop.set()
        for w in workers.values(): w.join()
        for ip, s in senders.items():
            stats = s.stats()
            result['streams'][ip]['stats'] = stats
            duration = result['streams'][ip].get('requested_seconds', 0)
            result['streams'][ip]['sender_complete'] = (duration > 0 and stats['packets'] == int(duration*44100/251) and stats['clock_requests'] > 0 and ip not in worker_errors)
            s.close()
        if changed:
            operations = [(ip + ' standalone', lambda ip=ip: av(ip, 'BecomeCoordinatorOfStandaloneGroup')) for ip,_ in targets]
            for ip,_ in devices:
                operations.extend([(ip + ' source', lambda ip=ip: av(ip, 'SetAVTransportURI', CurrentURI=before[ip]['media']['CurrentURI'], CurrentURIMetaData=before[ip]['media']['CurrentURIMetaData'])),
                                   (ip + ' stop', lambda ip=ip: av(ip, 'Stop'))])
            for ip,_ in devices: operations.append((ip + ' volume', lambda ip=ip: rc(ip, 'SetVolume', DesiredVolume=before[ip]['volume']['CurrentVolume'])))
            for ip,_ in devices: operations.append((ip + ' mute', lambda ip=ip: rc(ip, 'SetMute', DesiredMute=before[ip]['mute']['CurrentMute'])))
            for label, operation in operations:
                try: operation()
                except Exception as exc: result['restore_errors'].append(dict(step=label, error=str(exc)))
            result['verified'] = {}
            for ip,uid in devices:
                try:
                    after = snapshot(ip)
                    checks = {k:after[k] == before[ip][k] for k in ('transport','mute','volume')}
                    checks['source'] = all(after['media'].get(k) == before[ip]['media'].get(k) for k in ('CurrentURI','CurrentURIMetaData'))
                    checks['standalone'] = standalone(after,uid)
                    result['verified'][ip] = checks
                except Exception as exc: result['restore_errors'].append(dict(step=ip + ' verification', error=str(exc)))
        result['passed'] = (not result.get('error') and not result['restore_errors'] and
                            bool(result.get('checks')) and all(result['checks'].values()) and
                            all(s.get('sender_complete') for s in result['streams'].values()) and
                            len(result.get('verified', {})) == 3 and all(all(c.values()) for c in result['verified'].values()))
        save()
    print(json.dumps({k:result[k] for k in ('passed','error','checks','streams','verified','restore_errors') if k in result}, indent=2))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('first','first-id','second','second-id','coordinator','coordinator-id','output'):
        p.add_argument('--' + name, required=True)
    p.add_argument('--seconds', type=int, default=120)
    p.add_argument('--first-stop', type=int, default=45)
    args = p.parse_args()
    if not run(args)['passed']: raise SystemExit(1)

if __name__ == '__main__': main()
