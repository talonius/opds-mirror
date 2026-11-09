"""HTTP session with retries, a polite delay between requests, and streaming downloads."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


@contextlib.contextmanager
def _quiet_insecure(verify: bool):
    """With verify_ssl = false we log that once per server; urllib3 would warn on every request."""
    if verify:
        yield
        return
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
        yield

CHUNK = 1024 * 256


@dataclass
class DownloadResult:
    path: Path
    sha256: str
    size: int
    content_type: str
    content_disposition: str | None


class Client:
    def __init__(self, user_agent: str, timeout: float = 60.0, delay: float = 0.0, retries: int = 4):
        self.timeout = timeout
        self.delay = delay
        self.verify = True  # set to False to skip TLS certificate checks
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        retry = Retry(
            total=retries,
            backoff_factor=2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "HEAD"),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _wait(self) -> None:
        if self.delay > 0:
            remaining = self.delay - (time.monotonic() - self._last)
            if remaining > 0:
                time.sleep(remaining)
        self._last = time.monotonic()

    def fetch(self, url: str) -> bytes:
        self._wait()
        log.debug("GET %s", url)
        with _quiet_insecure(self.verify):
            resp = self.session.get(url, timeout=(10, self.timeout), verify=self.verify)
        resp.raise_for_status()
        return resp.content

    def download(
        self, url: str, dest: Path, on_chunk: Callable[[int, int | None], None] | None = None
    ) -> DownloadResult:
        """Stream ``url`` to ``dest`` while hashing it. ``dest`` is removed on failure."""
        self._wait()
        log.debug("GET %s -> %s", url, dest)
        digest = hashlib.sha256()
        size = 0
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with _quiet_insecure(self.verify), self.session.get(
                url, timeout=(10, self.timeout), stream=True, verify=self.verify
            ) as resp:
                resp.raise_for_status()
                expected = resp.headers.get("Content-Length")
                total = int(expected) if expected and expected.isdigit() else None
                with dest.open("wb") as fh:
                    for chunk in resp.iter_content(CHUNK):
                        fh.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                        if on_chunk:
                            on_chunk(size, total)
                if expected and resp.headers.get("Content-Encoding") is None and int(expected) != size:
                    raise IOError(f"incomplete download: got {size} of {expected} bytes")
                return DownloadResult(
                    path=dest,
                    sha256=digest.hexdigest(),
                    size=size,
                    content_type=resp.headers.get("Content-Type", ""),
                    content_disposition=resp.headers.get("Content-Disposition"),
                )
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
