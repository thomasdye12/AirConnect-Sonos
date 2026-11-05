#!/usr/bin/env python3
"""Apply the capacity-only change to the pinned multi-client NQPTP source.

No shared memory ABI changes; rebuild NQPTP afterwards. Python 3.4+.
"""
import argparse
import os


def expand(source):
    header = os.path.join(source, 'nqptp.h')
    with open(header) as f:
        text = f.read()
    with open(os.path.join(source, 'nqptp-clock-sources.h')) as f:
        clients = f.read()
    with open(os.path.join(source, 'nqptp-shm-structures.h')) as f:
        shared = f.read()
    if 'clock_source_private_data clocks_private[MAX_CLOCKS];' not in clients or '#define NQPTP_SHM_STRUCTURES_VERSION 11' not in shared:
        raise ValueError('Expected pinned per-client NQPTP with shared-memory version 11')
    old, new = '#define MAX_CLIENTS 16', '#define MAX_CLIENTS 32'
    if text.count(new) == 1:
        return False
    if text.count(old) != 1:
        raise ValueError('Unexpected MAX_CLIENTS definition')
    with open(header, 'w') as f:
        f.write(text.replace(old, new))
    return True


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source')
    a = p.parse_args()
    print('Applied 32-client capacity' if expand(a.source) else 'Already configured for 32 clients')
