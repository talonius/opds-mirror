"""Periodic "still working" log lines, so long quiet stretches don't look like a hang."""

from __future__ import annotations

import time

DEFAULT_INTERVAL = 5.0


class Ticker:
    """``due()`` returns True at most once every ``interval`` seconds."""

    def __init__(self, interval: float = DEFAULT_INTERVAL):
        self.interval = interval
        self._last = time.monotonic()

    def due(self) -> bool:
        now = time.monotonic()
        if now - self._last >= self.interval:
            self._last = now
            return True
        return False


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
