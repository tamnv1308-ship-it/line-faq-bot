"""Read-only OS probe. Never call Playwright from the heartbeat thread."""
import os
from pathlib import Path
import subprocess
import threading
import time


def process_rows(pid=None):
    selection = ['-p', str(pid)] if pid is not None else ['-ax']
    result = subprocess.run(['/bin/ps'] + selection + ['-o', 'pid=,ppid=,stat=,comm='],
                            capture_output=True, text=True, timeout=2)
    if result.returncode not in (0, 1) or (result.returncode and result.stderr.strip()):
        raise OSError('Process probe unavailable')
    rows = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) == 4 and parts[0].isdigit() and parts[1].isdigit():
            rows.append((int(parts[0]), int(parts[1]), parts[2], parts[3]))
    return rows


class DriverProbe:
    def __init__(self, parent_pid, executable, rows=process_rows):
        self.parent_pid = parent_pid
        self.executable = str(Path(executable).resolve())
        self.rows = rows
        self.pid = None
        self.state = 'unverified'
        self.checked_at = None
        self.lock = threading.Lock()

    def sample(self):
        with self.lock:return self._sample()

    def _sample(self):
        now = time.monotonic()
        if self.checked_at is not None and now - self.checked_at < 5:return self.state
        self.checked_at = now
        try:
            matches = [r for r in self.rows(self.pid)
                       if r[1] == self.parent_pid and str(Path(r[3]).resolve()) == self.executable
                       and 'Z' not in r[2]]
            if self.pid is None:
                if len(matches) != 1:self.state = 'unverified';return self.state
                self.pid = matches[0][0]
            self.state = 'alive' if len(matches) == 1 and matches[0][0] == self.pid else 'dead'
        except (OSError, subprocess.SubprocessError):
            self.state = 'unverified'
        return self.state


def own_driver_probe():
    import playwright
    executable = Path(playwright.__file__).resolve().parent / 'driver' / 'node'
    return DriverProbe(os.getpid(), executable)
