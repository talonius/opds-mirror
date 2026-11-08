"""SQLite index of every book file we know about, used to spot duplicates.

A book is a duplicate when the same *format* already exists and any of these
match: the file's SHA-256 hash, an ISBN, or the normalised author + title.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .keys import normalize_format, title_key
from .metadata import FileMetadata, metadata_from_path, read_metadata

log = logging.getLogger(__name__)

EBOOK_EXTENSIONS = {
    "epub", "kepub", "pdf", "mobi", "azw", "azw3", "azw4", "prc", "fb2", "cbz", "cbr",
    "cb7", "djvu", "rtf", "txt", "lit", "docx", "odt", "htmlz", "txtz", "lrf", "pdb",
    "mp3", "m4b",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    format TEXT NOT NULL,
    title_key TEXT,
    origin TEXT NOT NULL            -- 'library' or 'mirror'
);
CREATE INDEX IF NOT EXISTS files_sha256 ON files(sha256);
CREATE INDEX IF NOT EXISTS files_title ON files(title_key, format);
CREATE TABLE IF NOT EXISTS isbns (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    isbn TEXT NOT NULL,
    format TEXT NOT NULL,
    PRIMARY KEY (file_id, isbn)
);
CREATE INDEX IF NOT EXISTS isbns_isbn ON isbns(isbn, format);
-- Every remote download link we've dealt with, so cron runs don't re-download
-- duplicates we already threw away.
CREATE TABLE IF NOT EXISTS remote (
    url TEXT PRIMARY KEY,
    server TEXT NOT NULL,
    outcome TEXT NOT NULL,          -- 'downloaded' or 'duplicate'
    reason TEXT,
    seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_of(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".kepub.epub"):
        return "kepub"
    if name.endswith(".fb2.zip"):
        return "fb2"
    return normalize_format(path.suffix)


@dataclass
class ScanStats:
    scanned: int = 0
    hashed: int = 0
    removed: int = 0


class BookIndex:
    def __init__(self, db_path: Path):
        if str(db_path) != ":memory:":
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # ---- adding files -------------------------------------------------

    def add_file(self, path: Path, sha256: str, fmt: str, meta: FileMetadata, origin: str) -> None:
        st = path.stat()
        key = title_key(meta.authors, meta.title)
        with self.db:
            self.db.execute("DELETE FROM files WHERE path = ?", (str(path),))
            cur = self.db.execute(
                "INSERT INTO files (path, size, mtime_ns, sha256, format, title_key, origin)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (str(path), st.st_size, st.st_mtime_ns, sha256, fmt, key, origin),
            )
            self.db.executemany(
                "INSERT OR IGNORE INTO isbns (file_id, isbn, format) VALUES (?, ?, ?)",
                [(cur.lastrowid, isbn, fmt) for isbn in meta.isbns],
            )

    def scan(self, root: Path, origin: str) -> ScanStats:
        """Index every ebook under ``root``, re-hashing only new or changed files."""
        stats = ScanStats()
        if not root.is_dir():
            log.warning("library folder not found: %s", root)
            return stats
        known = {
            row[0]: (row[1], row[2])
            for row in self.db.execute(
                "SELECT path, size, mtime_ns FROM files WHERE path LIKE ? ESCAPE '\\'",
                (_like_prefix(root),),
            )
        }
        present: set[str] = set()
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            here = Path(dirpath)
            for name in filenames:
                path = here / name
                fmt = format_of(path)
                if fmt not in EBOOK_EXTENSIONS:
                    continue
                stats.scanned += 1
                key = str(path)
                present.add(key)
                try:
                    st = path.stat()
                    if known.get(key) == (st.st_size, st.st_mtime_ns):
                        continue
                    meta = read_metadata(path, fmt)
                    if (not meta.title or not meta.authors) and len(path.relative_to(root).parts) >= 3:
                        guess = metadata_from_path(path)
                        meta.title = meta.title or guess.title
                        meta.authors = meta.authors or guess.authors
                    self.add_file(path, sha256_file(path), fmt, meta, origin)
                    stats.hashed += 1
                except OSError as exc:
                    log.warning("could not index %s: %s", path, exc)
        gone = [p for p in known if p not in present]
        with self.db:
            self.db.executemany("DELETE FROM files WHERE path = ?", [(p,) for p in gone])
        stats.removed = len(gone)
        log.info("indexed %s: %d files, %d hashed, %d removed", root, stats.scanned, stats.hashed, stats.removed)
        return stats

    # ---- duplicate checks ---------------------------------------------

    def find_duplicate(
        self,
        fmt: str,
        *,
        sha256: str | None = None,
        isbns: list[str] = (),
        key: str | None = None,
    ) -> str | None:
        """Return a reason string if a matching book already exists, else None.

        The hash check ignores format (identical bytes are identical books);
        ISBN and author+title checks require the same format.
        """
        if sha256:
            row = self.db.execute("SELECT path FROM files WHERE sha256 = ? LIMIT 1", (sha256,)).fetchone()
            if row:
                return f"same file as {row[0]}"
        for isbn in isbns:
            row = self.db.execute(
                "SELECT f.path FROM isbns i JOIN files f ON f.id = i.file_id"
                " WHERE i.isbn = ? AND i.format = ? LIMIT 1",
                (isbn, fmt),
            ).fetchone()
            if row:
                return f"ISBN {isbn} matches {row[0]}"
        if key:
            row = self.db.execute(
                "SELECT path FROM files WHERE title_key = ? AND format = ? LIMIT 1", (key, fmt)
            ).fetchone()
            if row:
                return f"author and title match {row[0]}"
        return None

    def find_mirror_copy(self, isbns: list[str] = (), key: str | None = None) -> Path | None:
        """Find a file of the same book (any format) already in the mirror."""
        for isbn in isbns:
            row = self.db.execute(
                "SELECT f.path FROM isbns i JOIN files f ON f.id = i.file_id"
                " WHERE i.isbn = ? AND f.origin = 'mirror' LIMIT 1",
                (isbn,),
            ).fetchone()
            if row:
                return Path(row[0])
        if key:
            row = self.db.execute(
                "SELECT path FROM files WHERE title_key = ? AND origin = 'mirror' LIMIT 1", (key,)
            ).fetchone()
            if row:
                return Path(row[0])
        return None

    # ---- remote links ---------------------------------------------------

    def remote_outcome(self, url: str) -> str | None:
        row = self.db.execute("SELECT outcome FROM remote WHERE url = ?", (url,)).fetchone()
        return row[0] if row else None

    def record_remote(self, url: str, server: str, outcome: str, reason: str | None = None) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO remote (url, server, outcome, reason) VALUES (?, ?, ?, ?)",
                (url, server, outcome, reason),
            )


def _like_prefix(root: Path) -> str:
    prefix = str(root).rstrip(os.sep) + os.sep
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
