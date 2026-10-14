"""Verify late completion/failure cannot touch a helper released to another session."""
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import group_receiver_probe as probe
from test_group_receiver_probe import A, B, UA, UB, Household, FakeSocket


class HelperReuseTests(unittest.TestCase):
    def test_released_helper_is_untouched_on_completion_and_failure(self):
        for fail_sender in (False, True):
            with self.subTest(fail_sender=fail_sender):
                self.exercise(fail_sender)

    def exercise(self, fail_sender):
        household = Household()
        call_original = household.call
        clock, released = [0.0], {}
        def call(ip, path, service, name, args, **kwargs):
            if name == 'BecomeGroupCoordinator': household.joined = False
            result = call_original(ip, path, service, name, args)
            if name == 'ChangeTransportSettings': return {'http_status': 200, 'xml': '<response/>'}
            return result
        class Lease:
            def __init__(self, identity, *args): self.identity, self.done = identity, False
            def __enter__(self): return self
            def release(self):
                if not self.done:
                    released[self.identity] = len(household.calls)
                    self.done = True
            def __exit__(self, *args): self.release()
        class Event:
            flag = False
            def set(self): self.flag = True
            def is_set(self): return self.flag
            def wait(self, *args): return True
        class Thread:
            def __init__(self, target): self.target, self.alive = target, True
            def start(self): pass
            def is_alive(self): return self.alive
            def join(self, *args):
                clock[0] += 1
                if clock[0] >= 5 and self.alive:
                    self.target()
                    self.alive = False
        class Sender:
            clock_port = 12345
            def __init__(self, *args): self.packets = 0
            def close(self): pass
            def write(self, pcm):
                if fail_sender: raise OSError('late sender failure')
                self.packets += 1
            def stats(self): return dict(packets=self.packets, clock_requests=int(self.packets > 0), late_packets=0)
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            for target, attr, replacement in ((probe, 'call', call), (probe, 'DeviceLease', Lease),
                    (probe, 'NativeSender', Sender), (probe.socket, 'socket', lambda *a: FakeSocket()),
                    (probe.time, 'monotonic', lambda: clock[0]), (probe.threading, 'Thread', Thread),
                    (probe.threading, 'Event', Event)):
                stack.enter_context(patch.object(target, attr, replacement))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            result = probe.run(SimpleNamespace(receiver=A, receiver_id=UA, coordinator=B, coordinator_id=UB,
                output=str(Path(directory) / 'result.json'), seconds=12, handoff_to_synthetic=False,
                release_coordinator=False, reset_helper_group=False, promote_receiver=True, promotion_mode='detach'))
        self.assertTrue(result['helper_restored_early'])
        self.assertTrue(all(result['verified'][B].values()))
        self.assertFalse(any(ip == B for ip, _, _ in household.calls[released[UB]:]))
        self.assertTrue(all(result['verified'][A].values()))
        self.assertEqual(bool(result.get('error')), fail_sender)
