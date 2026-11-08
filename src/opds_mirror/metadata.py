"""Read title, authors and ISBNs from inside ebook files (EPUB, PDF, MOBI/AZW3)."""

from __future__ import annotations

import logging
import posixpath
import re
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from defusedxml import ElementTree as ET

from .keys import isbn13
from .opds import extract_isbns

log = logging.getLogger(__name__)
logging.getLogger("pypdf").setLevel(logging.ERROR)  # it warns loudly about odd but readable PDFs

OPF = "{http://www.idpf.org/2007/opf}"
DC = "{http://purl.org/dc/elements/1.1/}"
CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"


@dataclass
class FileMetadata:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    isbns: list[str] = field(default_factory=list)  # ISBN-13


def _isbn13s(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in extract_isbns(values):
        isbn = isbn13(raw)
        if isbn and isbn not in out:
            out.append(isbn)
    return out


def read_epub(path: Path) -> FileMetadata:
    with zipfile.ZipFile(path) as zf:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        rootfile = container.find(f".//{CONTAINER}rootfile")
        if rootfile is None:
            return FileMetadata()
        opf_path = posixpath.normpath(rootfile.get("full-path", ""))
        opf = ET.fromstring(zf.read(opf_path))
    meta = opf.find(f"{OPF}metadata")
    if meta is None:
        return FileMetadata()
    title_el = meta.find(f"{DC}title")
    title = " ".join((title_el.text or "").split()) if title_el is not None else ""
    authors = [" ".join((c.text or "").split()) for c in meta.findall(f"{DC}creator") if (c.text or "").strip()]
    identifiers = []
    for ident in meta.findall(f"{DC}identifier"):
        value = (ident.text or "").strip()
        scheme = (ident.get(f"{OPF}scheme") or ident.get("scheme") or "").lower()
        identifiers.append(f"isbn:{value}" if scheme == "isbn" else value)
    return FileMetadata(title=title, authors=authors, isbns=_isbn13s(identifiers))


def read_pdf(path: Path) -> FileMetadata:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - pypdf is a declared dependency
        return FileMetadata()
    info = PdfReader(str(path)).metadata or {}
    title = str(info.get("/Title") or "").strip()
    author = str(info.get("/Author") or "").strip()
    return FileMetadata(title=title, authors=[author] if author else [])


def read_mobi(path: Path) -> FileMetadata:
    """Parse the EXTH header of a MOBI/AZW/AZW3 file for author, title and ISBN."""
    data = path.read_bytes()
    if len(data) < 78 or data[60:68] not in (b"BOOKMOBI", b"TEXtREAd"):
        return FileMetadata()
    rec0 = struct.unpack_from(">I", data, 78)[0]
    if data[rec0 + 16 : rec0 + 20] != b"MOBI":
        return FileMetadata()
    header_len = struct.unpack_from(">I", data, rec0 + 20)[0]
    name_off, name_len = struct.unpack_from(">II", data, rec0 + 84)
    title = data[rec0 + name_off : rec0 + name_off + name_len].decode("utf-8", "replace")
    authors: list[str] = []
    identifiers: list[str] = []
    exth_flags = struct.unpack_from(">I", data, rec0 + 128)[0]
    exth = rec0 + 16 + header_len
    if exth_flags & 0x40 and data[exth : exth + 4] == b"EXTH":
        count = struct.unpack_from(">I", data, exth + 8)[0]
        pos = exth + 12
        for _ in range(count):
            rtype, rlen = struct.unpack_from(">II", data, pos)
            value = data[pos + 8 : pos + rlen].decode("utf-8", "replace").strip()
            if rtype == 100 and value:
                authors.append(value)
            elif rtype == 104:
                identifiers.append(f"isbn:{value}")
            elif rtype == 503 and value:
                title = value
            pos += rlen
    return FileMetadata(title=title.strip(), authors=authors, isbns=_isbn13s(identifiers))


READERS = {
    "epub": read_epub,
    "kepub": read_epub,
    "pdf": read_pdf,
    "mobi": read_mobi,
    "azw": read_mobi,
    "azw3": read_mobi,
    "prc": read_mobi,
}


def read_metadata(path: Path, fmt: str) -> FileMetadata:
    """Best effort: returns empty metadata for unknown formats or unreadable files."""
    reader = READERS.get(fmt)
    if reader is None:
        return FileMetadata()
    try:
        return reader(path)
    except Exception as exc:  # noqa: BLE001 - corrupt files shouldn't stop a scan
        log.debug("could not read metadata from %s: %s", path, exc)
        return FileMetadata()


_CALIBRE_ID = re.compile(r"\s*\(\d+\)$")


def metadata_from_path(path: Path) -> FileMetadata:
    """Guess author and title from an Author/Title/file layout (Calibre's, and ours)."""
    title = _CALIBRE_ID.sub("", path.parent.name)
    author = path.parent.parent.name
    return FileMetadata(title=title, authors=[author] if author else [])
