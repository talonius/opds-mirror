"""Download every book format from every configured server."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .http import Client
from .opds import Book, BookFormat, crawl
from .paths import book_dir, extension_for, safe_component

log = logging.getLogger(__name__)

STATE_DIR = ".opds-mirror"


@dataclass
class Stats:
    books: int = 0
    downloaded: int = 0
    skipped_existing: int = 0
    failed: int = 0
    would_download: int = 0
    failed_servers: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"{self.books} books seen",
            f"{self.downloaded} files downloaded",
            f"{self.skipped_existing} already present",
            f"{self.failed} failed",
        ]
        if self.would_download:
            parts.append(f"{self.would_download} would be downloaded (dry run)")
        if self.failed_servers:
            parts.append(f"servers failed: {', '.join(self.failed_servers)}")
        return ", ".join(parts)


class Mirror:
    def __init__(self, config: Config, client: Client | None = None, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.client = client or Client(config.user_agent, config.timeout, config.request_delay)
        self.stats = Stats()
        self.tmp_dir = config.output_dir / STATE_DIR / "tmp"

    def run(self) -> Stats:
        if not self.dry_run:
            self.tmp_dir.mkdir(parents=True, exist_ok=True)
            self._clean_tmp()
        for server in self.config.servers:
            log.info("crawling %s", server.name)
            try:
                for book in crawl(server.url, self.client.fetch, source=server.name):
                    self.stats.books += 1
                    self.process_book(book)
            except Exception as exc:  # noqa: BLE001 - one bad server shouldn't stop the rest
                log.error("server %s failed: %s", server.name, exc)
                self.stats.failed_servers.append(server.name)
        log.info("done: %s", self.stats.summary())
        return self.stats

    def _clean_tmp(self) -> None:
        for leftover in self.tmp_dir.glob("*.part"):
            leftover.unlink(missing_ok=True)

    def process_book(self, book: Book) -> None:
        target_dir = book_dir(self.config.output_dir, book.authors, book.title)
        file_stem = safe_component(book.title, fallback="Unknown Title")
        for fmt in book.formats:
            try:
                self.process_format(book, fmt, target_dir, file_stem)
            except Exception as exc:  # noqa: BLE001 - keep going with the next file
                self.stats.failed += 1
                log.warning("failed %r (%s) from %s: %s", book.title, fmt.url, book.source, exc)

    def process_format(self, book: Book, fmt: BookFormat, target_dir: Path, file_stem: str) -> None:
        guessed = target_dir / f"{file_stem}.{extension_for(fmt.mime, fmt.url)}"
        if guessed.exists():
            self.stats.skipped_existing += 1
            log.debug("already have %s", guessed)
            return

        if self.dry_run:
            self.stats.would_download += 1
            log.info("would download %s", guessed.relative_to(self.config.output_dir))
            return

        tmp = self.tmp_dir / f"{uuid.uuid4().hex}.part"
        result = self.client.download(fmt.url, tmp)
        try:
            ext = extension_for(result.content_type or fmt.mime, fmt.url, result.content_disposition)
            final = target_dir / f"{file_stem}.{ext}"
            if final.exists():
                self.stats.skipped_existing += 1
                log.debug("already have %s", final)
                return
            target_dir.mkdir(parents=True, exist_ok=True)
            os.replace(tmp, final)
            self.stats.downloaded += 1
            log.info("downloaded %s (%d bytes)", final.relative_to(self.config.output_dir), result.size)
        finally:
            tmp.unlink(missing_ok=True)
