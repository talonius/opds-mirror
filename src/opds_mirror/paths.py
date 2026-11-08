"""Turn book metadata into safe file and folder names."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlparse

MAX_COMPONENT = 120
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

MIME_EXTENSIONS = {
    "application/epub+zip": "epub",
    "application/kepub+zip": "kepub.epub",
    "application/pdf": "pdf",
    "application/x-mobipocket-ebook": "mobi",
    "application/x-mobi8-ebook": "azw3",
    "application/vnd.amazon.ebook": "azw",
    "application/vnd.amazon.mobi8-ebook": "azw3",
    "application/x-mobi": "mobi",
    "application/x-fictionbook+xml": "fb2",
    "application/x-zip-compressed-fb2": "fb2.zip",
    "application/vnd.comicbook+zip": "cbz",
    "application/x-cbz": "cbz",
    "application/vnd.comicbook-rar": "cbr",
    "application/x-cbr": "cbr",
    "application/x-cb7": "cb7",
    "image/vnd.djvu": "djvu",
    "application/rtf": "rtf",
    "text/rtf": "rtf",
    "text/plain": "txt",
    "text/html": "html",
    "application/x-ms-reader": "lit",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.oasis.opendocument.text": "odt",
    "application/zip": "zip",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4b",
}

# Formats Calibre names in its download URLs, e.g. /get/epub/12/Library.
KNOWN_FORMATS = {
    "epub", "kepub", "pdf", "mobi", "azw", "azw3", "azw4", "fb2", "cbz", "cbr",
    "cb7", "djvu", "rtf", "txt", "lit", "docx", "odt", "htmlz", "txtz", "lrf",
    "pdb", "prc", "zip", "mp3", "m4b",
}

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_component(name: str, fallback: str = "Unknown") -> str:
    """Make one path component that's valid on Windows, macOS and Linux."""
    name = unicodedata.normalize("NFC", name or "")
    name = _BAD_CHARS.sub("_", name)
    name = " ".join(name.split())
    name = name.strip(" .")
    if len(name) > MAX_COMPONENT:
        name = name[:MAX_COMPONENT].rstrip(" .")
    if not name:
        name = fallback
    if name.split(".")[0].upper() in WINDOWS_RESERVED:
        name = f"{name}_"
    return name


def author_folder(authors: list[str]) -> str:
    authors = [a for a in authors if a and a.strip()]
    if not authors:
        return "Unknown Author"
    return safe_component(" & ".join(authors), fallback="Unknown Author")


def book_dir(output_dir: Path, authors: list[str], title: str) -> Path:
    return output_dir / author_folder(authors) / safe_component(title, fallback="Unknown Title")


def extension_for(mime: str, url: str, content_disposition: str | None = None) -> str:
    """Pick a file extension from the server's filename, the MIME type, or the URL."""
    if content_disposition:
        match = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?", content_disposition, re.I)
        if match:
            filename = unquote(match.group(1)).strip()
            lowered = filename.lower()
            if lowered.endswith(".kepub.epub"):
                return "kepub.epub"
            if "." in filename:
                ext = filename.rsplit(".", 1)[1].lower()
                if ext and len(ext) <= 6 and ext.isalnum():
                    return ext

    base_mime = (mime or "").split(";")[0].strip().lower()
    if base_mime in MIME_EXTENSIONS:
        return MIME_EXTENSIONS[base_mime]

    # Calibre: /get/<fmt>/<id>/...   Calibre-Web: /opds/download/<id>/<fmt>/
    segments = [s.lower() for s in urlparse(url).path.split("/") if s]
    for seg in segments:
        if seg in KNOWN_FORMATS:
            return "kepub.epub" if seg == "kepub" else seg
    last = segments[-1] if segments else ""
    if "." in last:
        ext = last.rsplit(".", 1)[1]
        if ext.isalnum() and len(ext) <= 6:
            return ext
    return "bin"
