#!/usr/bin/env python3
"""Bounded UDP receiver probe using an ordinary, stopped Sonos coordinator.

No AudioIn/VirtualLineIn actions and no Connect-specific setup. This still uses
another physical speaker for group membership; it is not an independent backend.
Synthetic handoff is bounded research: current live tests lose the receiver after
about 76 seconds when the coordinator is absent from trusted topology.
Requires two stopped standalone speakers and verifies restoration of both.
Muted by default, including with a nonzero test signal. Audible testing is opt-in.
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
from probe_pcm import pcm_packet, load_wav
from device_lease import DeviceLease


def validate_options(args):
    if not 1 <= args.seconds <= 120:
        raise ValueError('Probe duration must be 1..120 seconds')
    signal = getattr(args, 'signal', 'silence')
    if signal not in ('silence', 'tone'):
        raise ValueError('Unknown test signal')
    if getattr(args, 'wav', None) and (signal != 'silence' or args.handoff_to_synthetic):
        raise ValueError('WAV cannot combine with a generated tone or synthetic handoff')
    if not 0 <= getattr(args, 'test_volume', 15) <= 35:
        raise ValueError('Test volume must be 0..35')
    if getattr(args, 'audible', False):
        if (signal != 'tone' and not getattr(args, 'wav', None)) or args.seconds > 30 or args.handoff_to_synthetic:
            raise ValueError('Audible tests require tone or WAV, at most 30 seconds, and no synthetic handoff')
        if getattr(args, 'promotion_mode', 'retain') == 'resume':
            raise ValueError('The failed resume experiment is restricted to muted testing')
    delay = getattr(args, 'promotion_delay', 3)
    if not 3 <= delay <= 30:
        raise ValueError('Promotion delay must be 3..30 seconds')
    if getattr(args, 'promote_receiver', False):
        if args.handoff_to_synthetic or args.seconds < delay + 2:
            raise ValueError('Promotion requires two seconds after the delay and no synthetic handoff')
    elif getattr(args, 'promotion_mode', 'retain') != 'retain':
        raise ValueError('Promotion mode requires receiver promotion')
    if args.release_coordinator and not args.handoff_to_synthetic:
        raise ValueError('Coordinator release requires synthetic handoff')
    if args.reset_helper_group and not args.release_coordinator:
        raise ValueError('Helper reset requires coordinator release')

def virtual_identity(receiver_id):
    return 'RINCON_02' + hashlib.sha256(receiver_id.encode()).hexdigest()[:10].upper() + '01400'


def promotion_arguments(coordinator_id, group_id, settings, uri):
    """State-transfer probe; empty transport source is deliberately diagnostic.

    The firmware parser may leave default transport settings when the final
    source is empty. Acceptance must never be treated as a working UDP sink.
    """
    return dict(InstanceID=0, CurrentCoordinator=coordinator_id,
                CurrentGroupID=group_id, OtherMembers='',
                TransportSettings=settings.rsplit(',', 1)[0] + ',',
                CurrentURI=uri, CurrentURIMetaData='', SleepTimerState='',
                AlarmState='', StreamRestartState='', SharedQueueTrackList='',
                PrivateQueueTrackList='', CurrentVLIState='')


def group_for(topology, uid):
    return next((g for g in ET.fromstring(topology['ZoneGroupState']).iter('ZoneGroup')
                 if any(m.get('UUID') == uid for m in g.iter('ZoneGroupMember'))), None)


def standalone(snapshot, uid):
    group = group_for(snapshot['topology'], uid)
    return group is not None and group.get('Coordinator') == uid and len(list(group.iter('ZoneGroupMember'))) == 1


def separated_in_both_views(receiver, helper, receiver_id, helper_id):
    return all(standalone(view, uid) for view in (receiver, helper)
               for uid in (receiver_id, helper_id))


def await_separation(snapshot, receiver, helper, receiver_id, helper_id, timeout=3):
    deadline = time.monotonic() + timeout
    while True:
        receiver_view, helper_view = snapshot(receiver), snapshot(helper)
        separated = separated_in_both_views(receiver_view, helper_view, receiver_id, helper_id)
        if separated or time.monotonic() >= deadline:
            return separated, receiver_view, helper_view
        time.sleep(.15)


def phase_checks(phase, receiver_id, promote=False, promotion_mode='retain'):
    """Keep sender progress separate from claimed playback/session success."""
    stats = phase['stats']
    phase['sender_check_passed'] = (phase.get('setup_accepted', False) and
        not phase.get('error') and phase.get('duration_seconds', 0) > 0 and
        stats['clock_requests'] > 0 and
        stats['packets'] == int(phase['duration_seconds'] * 44100 / 251))
    phase['transport_check_passed'] = (phase['sender_check_passed'] and
        phase.get('state', {}).get('CurrentTransportState') == 'PLAYING' and
        phase.get('state', {}).get('CurrentTransportStatus') == 'OK')
    if promote:
        phase['promotion_check_passed'] = (phase.get('promotion_accepted', False) and
            phase['transport_check_passed'] and
            phase.get('receiver_group_coordinator') == receiver_id and
            (promotion_mode == 'retain' or
             (phase.get('helper_standalone', False) and phase.get('receiver_standalone', False))))
        phase['transport_check_passed'] = phase['promotion_check_passed']


def record_checkpoint(phase, name, sender, started):
    phase.setdefault('checkpoints', {})[name] = dict(
        elapsed=round(time.monotonic() - started, 4), stats=sender.stats())


def interval_progress(phase, start, end):
    """Sender-side deltas; these never imply that samples were rendered."""
    points = phase.get('checkpoints', {})
    if start not in points or end not in points:
        return None
    a, b = points[start], points[end]
    if b['elapsed'] < a['elapsed']:
        raise ValueError('Checkpoints out of order')
    delta = {key: b['stats'][key] - a['stats'][key]
             for key in ('packets', 'clock_requests', 'late_packets')}
    if any(value < 0 for value in delta.values()):
        raise ValueError('Sender counters reset inside an interval')
    return dict(seconds=round(b['elapsed'] - a['elapsed'], 4),
                **delta, acoustic_playback_verified=False)


def run(args):
    validate_options(args)
    if args.receiver == args.coordinator or args.receiver_id == args.coordinator_id:
        raise ValueError('Use two different speakers')
    timeout = getattr(args, 'lock_timeout', 15)
    # Ownership covers snapshot through restoration. The helper can be released
    # early only after verified detach AND restoration, while receiver stays held.
    with DeviceLease(args.receiver_id, timeout), DeviceLease(args.coordinator_id, timeout) as helper_lease:
        return run_owned(args, helper_lease)


def run_owned(args, helper_lease):
    audible = getattr(args, 'audible', False)
    signal = getattr(args, 'signal', 'silence')
    wav_pcm = load_wav(args.wav, args.seconds) if getattr(args, 'wav', None) else None
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = {'actions': [], 'restore_errors': [], 'phases': [],
              'audio_in_calls': 0, 'virtual_line_in_calls': 0,
              'silent': not audible, 'signal': signal,
              'audible_requested': audible, 'acoustic_playback_verified': False,
              'independent_setup': False}
    if wav_pcm is not None:
        result['signal'] = 'wav'
        result['pcm_input'] = dict(bytes=len(wav_pcm), sha256=hashlib.sha256(wav_pcm).hexdigest(), fade_ms=200)
    virtual_id = virtual_identity(args.receiver_id)
    result['virtual_id'] = virtual_id
    result['started_utc'] = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    def save():
        output.write_text(json.dumps(result, indent=2) + '\n')
    def action(ip, name, arguments, path=AV, service='AVTransport', headers=None):
        response = call(ip, path, service, name, arguments, **({'headers': headers} if headers else {}))
        result['actions'].append({'at': round(time.monotonic()-started, 4), 'ip': ip,
                                  'action': name, 'arguments': arguments, 'response': response})
        if headers: result['actions'][-1]['headers'] = headers
        save()
        return values(response)
    def av(ip, name, **kw): return action(ip, name, {'InstanceID': 0, **kw})
    def rc(ip, name, **kw): return action(ip, name, {'InstanceID': 0, 'Channel': 'Master', **kw}, RC, 'RenderingControl')
    def snapshot(ip):
        return {'media': av(ip, 'GetMediaInfo'), 'transport': av(ip, 'GetTransportInfo'),
                'mute': rc(ip, 'GetMute'), 'volume': rc(ip, 'GetVolume'),
                'topology': action(ip, 'GetZoneGroupState', {}, '/ZoneGroupTopology/Control', 'ZoneGroupTopology')}
    def verify(ip, uid, after):
        checks = {k: after[k] == before[ip][k] for k in ('transport', 'mute', 'volume')}
        checks['source'] = all(after['media'].get(k) == before[ip]['media'].get(k) for k in ('CurrentURI', 'CurrentURIMetaData'))
        checks['standalone'] = standalone(after, uid)
        return checks
    devices = [(args.receiver, args.receiver_id), (args.coordinator, args.coordinator_id)]
    owned_devices = list(devices)
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
                if audible:
                    rc(args.receiver, 'SetVolume', DesiredVolume=getattr(args, 'test_volume', 15))
                    rc(args.receiver, 'SetMute', DesiredMute=0)
                else:
                    if rc(args.receiver, 'GetMute').get('CurrentMute') != '1':
                        raise RuntimeError('Receiver is not muted; refusing test signal')
                packet_count = int(duration * 44100 / 251)
                def produce():
                    try:
                        for index in range(packet_count):
                            if stop.is_set(): break
                            sender.write(wav_pcm[index * 1004:(index + 1) * 1004] if wav_pcm is not None
                                         else pcm_packet(index, packet_count, signal))
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
                record_checkpoint(phase, 'stream_started', sender, phase_start)
                phase['progress'] = []
                while worker.is_alive() and time.monotonic() - phase_start < duration + 5:
                    worker.join(1)
                    phase['progress'].append({'elapsed': round(time.monotonic() - phase_start, 3), **sender.stats()})
                    if (getattr(args, 'promote_receiver', False) and
                            time.monotonic() - phase_start >= getattr(args, 'promotion_delay', 3) and
                            not phase.get('promotion_attempted') and worker.is_alive()):
                        phase['promotion_attempted'] = True
                        phase['promotion_elapsed'] = round(time.monotonic() - phase_start, 3)
                        phase['before_promotion'] = snapshot(args.receiver)
                        record_checkpoint(phase, 'before_promotion', sender, phase_start)
                        promotion_mode = getattr(args, 'promotion_mode', 'retain')
                        promotion_group = (group.get('ID') if promotion_mode == 'retain' else
                                           group_for(before[args.receiver]['topology'], args.receiver_id).get('ID'))
                        phase['promotion_mode'] = promotion_mode
                        action(args.receiver, 'BecomeGroupCoordinator',
                               promotion_arguments(args.coordinator_id, promotion_group, settings,
                                                   'x-rincon-stream:' + virtual_id + ':0'),
                               headers={'x-sonos-clone-gc': '1'})
                        phase['promotion_accepted'] = True
                        phase['after_promotion'] = snapshot(args.receiver)
                        record_checkpoint(phase, 'promoted', sender, phase_start)
                        if promotion_mode != 'retain':
                            phase['helper_after_promotion'] = snapshot(args.coordinator)
                            phase['helper_already_released'] = separated_in_both_views(
                                phase['after_promotion'], phase['helper_after_promotion'],
                                args.receiver_id, args.coordinator_id)
                            if not phase['helper_already_released']:
                                separated, receiver_view, helper_view = await_separation(
                                    snapshot, args.receiver, args.coordinator, args.receiver_id, args.coordinator_id)
                                phase['helper_already_released'] = separated
                                phase['topology_after_settle'] = dict(receiver=receiver_view, helper=helper_view)
                            if not phase['helper_already_released']:
                                action(args.coordinator, 'RemoveMember', {'MemberID': args.receiver_id}, '/GroupManagement/Control', 'GroupManagement')
                                phase['remove_member_accepted'] = True
                                phase['helper_standalone_response'] = av(args.coordinator, 'BecomeCoordinatorOfStandaloneGroup')
                            phase['after_helper_detach'] = snapshot(args.receiver)
                            record_checkpoint(phase, 'helper_released', sender, phase_start)
                            # Do not retain or restore a helper underneath a later
                            # session. Release only after both topology views agree.
                            helper_after = snapshot(args.coordinator)
                            if not separated_in_both_views(phase['after_helper_detach'], helper_after,
                                                          args.receiver_id, args.coordinator_id):
                                raise RuntimeError('Detach not confirmed by both speakers; helper remains owned')
                            rc(args.coordinator, 'SetMute', DesiredMute=1)
                            av(args.coordinator, 'SetAVTransportURI',
                               CurrentURI=before[args.coordinator]['media']['CurrentURI'],
                               CurrentURIMetaData=before[args.coordinator]['media']['CurrentURIMetaData'])
                            av(args.coordinator, 'Stop')
                            rc(args.coordinator, 'SetVolume', DesiredVolume=before[args.coordinator]['volume']['CurrentVolume'])
                            rc(args.coordinator, 'SetMute', DesiredMute=before[args.coordinator]['mute']['CurrentMute'])
                            restored_helper = snapshot(args.coordinator)
                            checks = verify(args.coordinator, args.coordinator_id, restored_helper)
                            if not all(checks.values()):
                                raise RuntimeError('Helper restoration not verified; helper remains owned')
                            result.setdefault('verified', {})[args.coordinator] = checks
                            result.setdefault('after', {})[args.coordinator] = restored_helper
                            result['helper_released_snapshot'] = restored_helper
                            result['helper_restored_early'] = True
                            result['helper_lease_released_at'] = round(time.monotonic() - started, 4)
                            owned_devices.remove((args.coordinator, args.coordinator_id))
                            helper_lease.release()
                        if promotion_mode == 'resume':
                            av(args.receiver, 'Play', Speed=1)
                            phase['resume_accepted'] = True
                        phase['receiver_after_transition'] = snapshot(args.receiver)
                        if not audible and phase['receiver_after_transition']['mute'].get('CurrentMute') != '1':
                            raise RuntimeError('Receiver mute changed during transition')
                    save()
                if worker.is_alive(): raise RuntimeError('Sender exceeded bounded duration')
                if errors: raise RuntimeError(errors[0])
                record_checkpoint(phase, 'stream_finished', sender, phase_start)
                phase['reference_progress'] = interval_progress(phase, 'stream_started', 'before_promotion')
                phase['detached_progress'] = interval_progress(phase, 'helper_released', 'stream_finished')
                phase['media'] = av(args.receiver, 'GetMediaInfo')
                phase['coordinator_state'] = (result['helper_released_snapshot'] if result.get('helper_restored_early')
                                              else snapshot(args.coordinator))
                phase['helper_state_observation'] = 'at_lease_release' if result.get('helper_restored_early') else 'at_stream_end'
                phase['state'] = av(args.receiver, 'GetTransportInfo')
                phase['topology'] = action(args.receiver, 'GetZoneGroupState', {}, '/ZoneGroupTopology/Control', 'ZoneGroupTopology')
                phase['helper_standalone'] = standalone(phase['coordinator_state'], args.coordinator_id)
                receiver_group = group_for(phase['topology'], args.receiver_id)
                phase['receiver_group_coordinator'] = receiver_group.get('Coordinator') if receiver_group is not None else None
                phase['receiver_standalone'] = standalone({'topology': phase['topology']}, args.receiver_id)
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
                phase_checks(phase, args.receiver_id, getattr(args, 'promote_receiver', False),
                             getattr(args, 'promotion_mode', 'retain'))
                save()
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        if changed:
            # Break the temporary group before restoring either source. Keep both
            # muted until all source/state restoration attempts have completed.
            operations = [(ip + ' mute for restore', lambda ip=ip: rc(ip, 'SetMute', DesiredMute=1)) for ip, _ in owned_devices]
            operations.append(('receiver standalone', lambda: av(args.receiver, 'BecomeCoordinatorOfStandaloneGroup')))
            for ip, _ in owned_devices:
                operations += [(ip + ' source', lambda ip=ip: av(ip, 'SetAVTransportURI',
                    CurrentURI=before[ip]['media']['CurrentURI'], CurrentURIMetaData=before[ip]['media']['CurrentURIMetaData'])),
                    (ip + ' stopped', lambda ip=ip: av(ip, 'Stop'))]
            for ip, _ in owned_devices:
                operations.append((ip + ' volume', lambda ip=ip: rc(ip, 'SetVolume', DesiredVolume=before[ip]['volume']['CurrentVolume'])))
            for ip, _ in owned_devices:
                operations.append((ip + ' mute', lambda ip=ip: rc(ip, 'SetMute', DesiredMute=before[ip]['mute']['CurrentMute'])))
            for label, operation in operations:
                try: operation()
                except Exception as exc: result['restore_errors'].append({'step': label, 'error': str(exc)})
            result.setdefault('verified', {})
            for ip, uid in owned_devices:
                try:
                    after = snapshot(ip)
                    result.setdefault('after', {})[ip] = after
                    checks = verify(ip, uid, after)
                    result['verified'][ip] = checks
                except Exception as exc: result['restore_errors'].append({'step': ip + ' verification', 'error': str(exc)})
        save()
    summary = {k: result[k] for k in ('error', 'verified', 'restore_errors') if k in result}
    summary['phases'] = [{k: p[k] for k in ('name', 'setup_accepted', 'stats', 'state', 'error', 'sender_check_passed', 'transport_check_passed', 'helper_standalone', 'receiver_standalone', 'receiver_group_coordinator', 'reference_progress', 'detached_progress') if k in p} for p in result['phases']]
    print(json.dumps(summary, indent=2))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('receiver', 'receiver-id', 'coordinator', 'coordinator-id', 'output'):
        p.add_argument('--' + arg, required=True)
    p.add_argument('--seconds', type=int, choices=range(1, 121), default=3)
    p.add_argument('--lock-timeout', type=float, default=15, help='Maximum wait for device ownership, 0..60 seconds')
    p.add_argument('--handoff-to-synthetic', action='store_true', help='After group setup, test ChangeCoordinator to a synthetic identity')
    p.add_argument('--release-coordinator', action='store_true', help='After handoff, remove receiver from the real coordinator membership list')
    p.add_argument('--reset-helper-group', action='store_true', help='After RemoveMember, request standalone state on the helper to test group independence')
    p.add_argument('--signal', choices=('silence', 'tone'), default='silence', help='PCM payload; tone remains muted unless --audible is specified')
    p.add_argument('--wav', help='44.1 kHz stereo 16-bit PCM WAV; remains muted unless --audible is specified')
    p.add_argument('--audible', action='store_true', help='Unmute receiver for a tone or WAV test of at most 30 seconds')
    p.add_argument('--test-volume', type=int, default=15, help='Audible test volume, 0..35; original volume is restored')
    p.add_argument('--promotion-delay', type=int, default=3, help='Seconds before promotion, 3..30, leaving at least two seconds afterward')
    p.add_argument('--promote-receiver', action='store_true', help='Test receiver promotion while the same sender continues')
    p.add_argument('--promotion-mode', choices=('retain', 'detach', 'resume'), default='retain', help='Promotion: retain old group, restore own group and detach helper, or additionally request Play')
    args = p.parse_args()
    try: validate_options(args)
    except ValueError as exc: p.error(str(exc))
    result = run(args)
    if not result['phases'] or not all(p.get('transport_check_passed') for p in result['phases']) or result.get('error') or result['restore_errors'] or not all(all(v.values()) for v in result.get('verified', {}).values()):
        raise SystemExit(1)

if __name__ == '__main__': main()
