"""Same-user, same-host device ownership shared across native probe processes.

Do not unlink lock files: a replacement inode could admit two owners. These
advisory leases do not coordinate unrelated controllers or other hosts.
"""
import fcntl
import hashlib
import os
from pathlib import Path
import tempfile
import time


class DeviceLease:
    def __init__(self, identity, timeout=15, directory=None):
        if not 0 <= timeout <= 60:
            raise ValueError('Lease timeout must be 0..60 seconds')
        self.identity, self.timeout, self.fd = identity, timeout, None
        self.directory = Path(directory or Path(tempfile.gettempdir()) / ('airconnect-native-' + str(os.getuid())))

    def __enter__(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.directory / (hashlib.sha256(self.identity.encode()).hexdigest() + '.lock')
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.fd = fd
                    return self
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Sonos device is busy with another native session')
                    time.sleep(min(.05, max(0, deadline - time.monotonic())))
        except BaseException:
            os.close(fd)
            raise

    def release(self):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None

    def __exit__(self, *args):
        self.release()
