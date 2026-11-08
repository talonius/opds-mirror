"""A lock file so two runs (e.g. overlapping cron jobs) never work at the same time."""

from __future__ import annotations

import os
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None
    import msvcrt


class AlreadyRunning(RuntimeError):
    pass


class RunLock:
    """Exclusive, non-blocking lock. The OS releases it if the process dies."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        try:
            if fcntl:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            fh.close()
            raise AlreadyRunning(f"another opds-mirror run holds {self.path}") from None
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        self._fh = fh
        return self

    def __exit__(self, *exc) -> None:
        if self._fh:
            if fcntl:
                fcntl.flock(self._fh, fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None
