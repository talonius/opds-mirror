"""Download every new book format from every configured server."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .http import Client
from .index import BookIndex, format_of
from .keys import isbn13, normalize_format, title_key
from .metadata import read_metadata
from .opds import Book, BookFormat, crawl
from .paths import book_dir, extension_for, safe_component

log = logging.getLogger(__name__)

STATE_DIR = ".opds-mirror"


@dataclass
class Stats:
    books: int = 0
    downloaded: int = 0
    skipped_existing: int = 0
    skipped_known: int = 0
    skipped_duplicate: int = 0
    discarded_duplicate: int = 0
    failed: int = 0
    would_download: int = 0
    failed_servers: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [
            f"{self.books} books seen",
            f"{self.downloaded} files downloaded",
            f"{self.skipped_existing} already present",
            f"{self.skipped_known} handled on an earlier run",
            f"{self.skipped_duplicate} duplicates skipped before download",
            f"{self.discarded_duplicate} duplicates discarded after download",
            f"{self.failed} failed",
        ]
        if self.would_download:
            parts.append(f"{self.would_download} would be downloaded (dry run)")
        if self.failed_servers:
            parts.append(f"servers failed: {', '.join(self.failed_servers)}")
        return ", ".join(parts)


class Mirror:
    def __init__(
        self,
        config: Config,
        client: Client | None = None,
        dry_run: bool = False,
        recheck: bool = False,
    ):
        self.config = config
        self.dry_run = dry_run
        self.recheck = recheck
        self.client = client or Client(config.user_agent, config.timeout, config.request_delay)
        self.stats = Stats()
        self.tmp_dir = config.output_dir / STATE_DIR / "tmp"
        self.index: BookIndex | None = None

    def run(self) -> Stats:
        index_file = self.config.index_file
        if self.dry_run and not index_file.exists():
            index_file = Path(":memory:")  # a dry run leaves no trace on disk
        self.index = BookIndex(index_file)
        try:
            refresh_index(self.config, self.index)
            if not self.dry_run:
                self.tmp_dir.mkdir(parents=True, exist_ok=True)
                for leftover in self.tmp_dir.glob("*.part"):
                    leftover.unlink(missing_ok=True)
            for server in self.config.servers:
                log.info("crawling %s", server.name)
                try:
                    for book in crawl(server.url, self.client.fetch, source=server.name):
                        self.stats.books += 1
                        self.process_book(book)
                except Exception as exc:  # noqa: BLE001 - one bad server shouldn't stop the rest
                    log.error("server %s failed: %s", server.name, exc)
                    self.stats.failed_servers.append(server.name)
        finally:
            self.index.close()
        log.info("done: %s", self.stats.summary())
        return self.stats

    def process_book(self, book: Book) -> None:
        target_dir = book_dir(self.config.output_dir, book.authors, book.title)
        file_stem = safe_component(book.title, fallback="Unknown Title")
        # If another server already gave us this book in some format, put new
        # formats next to it rather than in a second, differently spelled folder.
        feed_isbns = [i for i in (isbn13(x) for x in book.isbns) if i]
        existing = self.index.find_mirror_copy(feed_isbns, title_key(book.authors, book.title))
        if existing is not None and existing.parent != target_dir:
            target_dir = existing.parent
            file_stem = existing.name[: -len(existing.suffix)] if existing.suffix else existing.name
            if file_stem.lower().endswith(".kepub"):
                file_stem = file_stem[: -len(".kepub")]
        for fmt in book.formats:
            try:
                self.process_format(book, fmt, target_dir, file_stem)
            except Exception as exc:  # noqa: BLE001 - keep going with the next file
                self.stats.failed += 1
                log.warning("failed %r (%s) from %s: %s", book.title, fmt.url, book.source, exc)

    def _record(self, url: str, server: str, outcome: str, reason: str | None = None) -> None:
        if not self.dry_run:
            self.index.record_remote(url, server, outcome, reason)

    def process_format(self, book: Book, fmt: BookFormat, target_dir: Path, file_stem: str) -> None:
        index = self.index
        if not self.recheck and index.remote_outcome(fmt.url):
            self.stats.skipped_known += 1
            return

        guessed_ext = extension_for(fmt.mime, fmt.url)
        guessed = target_dir / f"{file_stem}.{guessed_ext}"
        if guessed.exists():
            self.stats.skipped_existing += 1
            self._record(fmt.url, book.source, "downloaded", "already present")
            return

        # Cheap checks first, from the catalog's own metadata: no download needed.
        feed_isbns = [i for i in (isbn13(x) for x in book.isbns) if i]
        key = title_key(book.authors, book.title)
        reason = index.find_duplicate(normalize_format(guessed_ext), isbns=feed_isbns, key=key)
        if reason:
            self.stats.skipped_duplicate += 1
            log.info("skipping %r (%s): %s", book.title, guessed_ext, reason)
            self._record(fmt.url, book.source, "duplicate", reason)
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
            fmt_key = format_of(final)
            if final.exists():
                self.stats.skipped_existing += 1
                self._record(fmt.url, book.source, "downloaded", "already present")
                return

            # Now that we have the file: its hash, plus what's written inside it.
            meta = read_metadata(tmp, fmt_key)
            meta.title = book.title or meta.title
            meta.authors = book.authors or meta.authors
            meta.isbns = list(dict.fromkeys(feed_isbns + meta.isbns))
            reason = index.find_duplicate(
                fmt_key, sha256=result.sha256, isbns=meta.isbns, key=title_key(meta.authors, meta.title)
            )
            if reason:
                self.stats.discarded_duplicate += 1
                log.info("discarded %r (%s): %s", book.title, ext, reason)
                self._record(fmt.url, book.source, "duplicate", reason)
                return

            target_dir.mkdir(parents=True, exist_ok=True)
            os.replace(tmp, final)
            index.add_file(final, result.sha256, fmt_key, meta, origin="mirror")
            self._record(fmt.url, book.source, "downloaded")
            self.stats.downloaded += 1
            log.info("downloaded %s (%d bytes)", final.relative_to(self.config.output_dir), result.size)
        finally:
            tmp.unlink(missing_ok=True)


def refresh_index(config: Config, index: BookIndex) -> None:
    """Bring the index up to date with the library folders and the mirror itself."""
    for library in config.library_dirs:
        index.scan(library, origin="library")
    if config.output_dir.is_dir():
        index.scan(config.output_dir, origin="mirror")
