#!/usr/bin/env python3
"""Summarise the latest AP2 worker session without exposing raw household logs.

Read a saved journal export or stdin. This tool never contacts speakers, changes
volume, or treats transmitted PCM as proof of audible playback. Python 3.4+.
"""
import argparse
import json
import math
import re
import sys


def analyse(lines):
    result = fresh()
    closed = False
    for line in lines:
        if 'ap2 worker start:' in line:
            result = fresh()
            closed = False
            match = re.search(r'source=([\w.-]+)', line)
            if match:
                result['build'] = match.group(1)
            match = re.search(r'muted=(\d+)', line)
            if match:
                result['configured_muted'] = bool(int(match.group(1)))
        is_sample = 'ap2 PCM received=' in line
        is_close = 'ap2 worker closed rc=' in line
        if is_sample or is_close:
            values = dict((k, int(v)) for k, v in re.findall(r'(\w+)=(-?\d+)', line))
            # Legacy workers have no start marker. Counter resets and closed
            # sessions must not let an earlier successful stream mask this one.
            if closed or values.get('received', 0) < result['counters'].get('received', 0):
                result = fresh()
                closed = False
            result['counters'] = values
            for key in ('input_peak', 'output_peak'):
                if key in values:
                    old = result['peaks'][key]
                    result['peaks'][key] = max(values[key], old if old is not None else 0)
            if is_close:
                result['exit_code'] = values.get('rc')
                closed = True
        if re.search(r'native restore .*: FAILED', line):
            result['restoration_failed'] = True
        if 'ap2 worker failed' in line or 'ap2 worker: could not' in line or 'ap2 worker: invalid' in line:
            result['worker_error'] = True
    incoming, outgoing = result['peaks']['input_peak'], result['peaks']['output_peak']
    count = result['counters'].get('received', 0)
    if result['restoration_failed']:
        status = 'restoration_failed'
        advice = 'Check speaker state before another test; restoration was reported failed.'
    elif result['worker_error'] or result['exit_code'] not in (None, 0):
        status = 'worker_failed'
        advice = 'Inspect the private worker log for setup, timing, or transport failure.'
    elif not count:
        status = 'no_pcm_evidence'
        advice = 'No received PCM is recorded. Select the test destination and play music; allow at least five seconds for a diagnostic report.'
    elif incoming is None or outgoing is None:
        status = 'levels_unavailable'
        advice = 'This log lacks signal levels. Rebuild the diagnostic worker and capture a fresh session.'
    elif incoming <= 32:
        status = 'input_near_silent'
        advice = 'Input peaks are at or below about -60 dBFS. Check the source track and iPhone AirPlay volume; frame counts can include silence or dither.'
    elif outgoing <= 32:
        status = 'output_near_silent'
        advice = 'Input has signal but rendered PCM is near silent. Inspect deadline alignment, late frames and flushes.'
    else:
        status = 'pcm_signal_present'
        advice = 'Signal reached the PCM submitted to the native sender. Listen on the speaker; if silent, inspect speaker state, transport and timing.'
    result['status'], result['next_step'] = status, advice
    result['audible_playback_verified'] = False
    result['session_closed'] = closed
    result['peak_dbfs'] = dict((k, None if v is None or v == 0 else round(20 * math.log10(v / 32768.0), 1)) for k, v in result['peaks'].items())
    return result


def fresh():
    return dict(build=None, configured_muted=None, counters={},
                peaks=dict(input_peak=None, output_peak=None), exit_code=None,
                restoration_failed=False, worker_error=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', nargs='?', default='-', help='journal text file, or - for stdin')
    parser.add_argument('--json', action='store_true', help='print machine-readable summary')
    args = parser.parse_args()
    if args.log == '-':
        result = analyse(sys.stdin)
    else:
        with open(args.log, errors='replace') as stream:
            result = analyse(stream)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print('Latest recorded session: ' + result['status'].replace('_', ' '))
        print('Worker build: ' + (result['build'] or 'not recorded'))
        print('Session: ' + ('closed' if result['session_closed'] else 'no close recorded; live state unknown'))
        print('Frames: received={received}, late={late}, silence={silence}'.format(**dict(dict(received=0, late=0, silence=0), **result['counters'])))
        print('Peak sample levels: input={input_peak}, output={output_peak} (full scale 32768)'.format(**result['peaks']))
        if result['configured_muted']:
            print('This session was configured muted.')
        print(result['next_step'])
        print('Audio heard at the speaker is not verified by this report.')


if __name__ == '__main__':
    main()
