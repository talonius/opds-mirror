"""Parse OPDS 1.x (Atom) feeds and crawl a catalog to find every book.

Works with the Calibre content server (``/opds``) and Calibre-Web (``/opds``),
and should work with any other OPDS 1.x catalog.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterator
from urllib.parse import urldefrag, urljoin, urlparse

from defusedxml import ElementTree as ET

log = logging.getLogger(__name__)

ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/terms/}"
DC_ELEMENTS = "{http://purl.org/dc/elements/1.1/}"

ACQUISITION_REL = "http://opds-spec.org/acquisition"
# Acquisition variants that don't give you the actual book for free.
SKIPPED_ACQUISITION_RELS = {
    "http://opds-spec.org/acquisition/borrow",
    "http://opds-spec.org/acquisition/buy",
    "http://opds-spec.org/acquisition/sample",
    "http://opds-spec.org/acquisition/preview",
    "http://opds-spec.org/acquisition/subscribe",
}
# Feed/entry links that never lead to new books (or would only loop).
SKIPPED_NAV_RELS = {
    "self",
    "start",
    "up",
    "previous",
    "prev",
    "first",
    "last",
    "search",
    "http://opds-spec.org/facet",
    "http://opds-spec.org/image",
    "http://opds-spec.org/image/thumbnail",
    "http://opds-spec.org/thumbnail",
    "http://opds-spec.org/cover",
}

ISBN_RE = re.compile(r"(97[89][0-9]{10}|[0-9]{9}[0-9Xx])")


class NotAFeed(ValueError):
    """The page isn't an OPDS feed (e.g. a login page). Usually harmless."""


@dataclass
class BookFormat:
    url: str
    mime: str


@dataclass
class Book:
    """One book entry from a catalog, with every downloadable format."""

    id: str
    title: str
    authors: list[str]
    isbns: list[str] = field(default_factory=list)
    formats: list[BookFormat] = field(default_factory=list)
    source: str = ""


@dataclass
class Feed:
    entries_books: list[Book]
    nav_links: list[str]
    next_links: list[str]


def _is_atom_feed_type(mime: str) -> bool:
    return "atom+xml" in mime.lower()


def _text(el, path: str) -> str:
    found = el.find(path)
    if found is None or found.text is None:
        return ""
    return " ".join(found.text.split())


def extract_isbns(values: list[str]) -> list[str]:
    """Pull ISBN-10/13 strings out of identifiers such as ``urn:isbn:978...``."""
    out: list[str] = []
    for value in values:
        if not value:
            continue
        lowered = value.lower()
        if "isbn" not in lowered and not re.fullmatch(r"[0-9Xx\- ]{10,17}", value.strip()):
            continue
        digits = re.sub(r"[^0-9Xx]", "", value)
        match = ISBN_RE.search(digits)
        if match:
            isbn = match.group(1).upper()
            if isbn not in out:
                out.append(isbn)
    return out


def parse_feed(xml: bytes, base_url: str) -> Feed:
    """Parse one OPDS page into book entries, navigation links and next-page links."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        if xml.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html")):
            raise NotAFeed("got an HTML page, not a feed") from exc
        raise
    if root.tag != f"{ATOM}feed":
        raise NotAFeed(f"not an Atom feed (root element {root.tag!r})")

    next_links: list[str] = []
    for link in root.findall(f"{ATOM}link"):
        rel = (link.get("rel") or "").strip()
        href = link.get("href")
        if href and rel == "next":
            next_links.append(urljoin(base_url, href))

    books: list[Book] = []
    nav_links: list[str] = []
    for entry in root.findall(f"{ATOM}entry"):
        formats: list[BookFormat] = []
        entry_nav: list[str] = []
        for link in entry.findall(f"{ATOM}link"):
            rel = (link.get("rel") or "").strip()
            href = link.get("href")
            mime = (link.get("type") or "").strip()
            if not href:
                continue
            url = urljoin(base_url, href)
            if rel.startswith(ACQUISITION_REL):
                if rel in SKIPPED_ACQUISITION_RELS:
                    continue
                if _is_atom_feed_type(mime):
                    # Indirect acquisition (a feed describing the book); follow it.
                    entry_nav.append(url)
                else:
                    formats.append(BookFormat(url=url, mime=mime))
            elif rel not in SKIPPED_NAV_RELS and _is_atom_feed_type(mime):
                entry_nav.append(url)

        if formats:
            entry_id = _text(entry, f"{ATOM}id") or formats[0].url
            authors = [
                _text(a, f"{ATOM}name")
                for a in entry.findall(f"{ATOM}author")
                if _text(a, f"{ATOM}name")
            ]
            identifiers = [
                (el.text or "").strip()
                for el in entry.findall(f"{DC}identifier") + entry.findall(f"{DC_ELEMENTS}identifier")
            ]
            books.append(
                Book(
                    id=entry_id,
                    title=_text(entry, f"{ATOM}title") or "Unknown",
                    authors=authors,
                    isbns=extract_isbns(identifiers),
                    formats=formats,
                )
            )
        else:
            # A navigation entry: its feed links lead to more of the catalog.
            # Book entries' feed links (e.g. "more by this author") are skipped,
            # since every book is reachable from navigation anyway.
            nav_links.extend(entry_nav)

    return Feed(entries_books=books, nav_links=nav_links, next_links=next_links)


Fetcher = Callable[[str], bytes]


def crawl(root_url: str, fetch: Fetcher, source: str = "") -> Iterator[Book]:
    """Walk every feed reachable from ``root_url`` and yield each book once.

    Only follows feed links on the same host as ``root_url``. If the root page
    fails, the error is raised; any later page that fails to load or parse is
    logged and skipped so one bad page doesn't stop the run.
    """
    root_host = urlparse(root_url).netloc
    queue: deque[str] = deque([root_url])
    seen_urls: set[str] = {urldefrag(root_url).url}
    seen_books: set[str] = set()
    pages = 0

    while queue:
        url = queue.popleft()
        try:
            feed = parse_feed(fetch(url), url)
        except Exception as exc:  # noqa: BLE001 - keep crawling past bad pages
            if url == root_url:
                raise
            if isinstance(exc, NotAFeed):
                log.info("skipping %s: %s", url, exc)
            else:
                log.warning("skipping feed %s: %s", url, exc)
            continue
        pages += 1

        for book in feed.entries_books:
            if book.id in seen_books:
                continue
            seen_books.add(book.id)
            book.source = source or root_url
            yield book

        for link in feed.next_links + feed.nav_links:
            link = urldefrag(link).url
            if link in seen_urls or urlparse(link).netloc != root_host:
                continue
            seen_urls.add(link)
            queue.append(link)

    log.info("%s: crawled %d feed pages, found %d books", source or root_url, pages, len(seen_books))
