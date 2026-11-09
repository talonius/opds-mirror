from pathlib import Path

from opds_mirror.opds import crawl, extract_isbns, parse_feed

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_calibre_acquisition_feed():
    feed = parse_feed((FIXTURES / "calibre/newest.xml").read_bytes(), "http://h/opds/navcatalog/x")
    assert feed.next_links == ["http://h/opds/navcatalog/4f6e6577657374?offset=1"]
    # The "related" author link on a book entry is not followed.
    assert feed.nav_links == []
    [book] = feed.entries_books
    assert book.title == "The Left Hand: A Novel"
    assert book.authors == ["Jane Doe", "John Roe"]
    assert book.isbns == ["9780306406157"]
    assert [(f.url, f.mime) for f in book.formats] == [
        ("http://h/get/epub/1/Calibre_Library", "application/epub+zip"),
        ("http://h/get/pdf/1/Calibre_Library", "application/pdf"),
    ]


def test_parse_navigation_feed_skips_start_and_search():
    feed = parse_feed((FIXTURES / "calibreweb/root.xml").read_bytes(), "http://h/opds")
    assert feed.entries_books == []
    assert feed.nav_links == ["http://h/opds/books", "http://h/opds/discover"]


def test_extract_isbns():
    assert extract_isbns(["urn:isbn:0-306-40615-2", "urn:uuid:abc", "9780141439600", "ISBN 123"]) == [
        "0306406152",
        "9780141439600",
    ]


def test_crawl_visits_each_book_once_and_stays_on_host():
    pages = {
        "http://h/calibre/opds": "calibre/root.xml",
        "http://h/opds/navcatalog/4f6e6577657374": "calibre/newest.xml",
        "http://h/opds/navcatalog/4f6e6577657374?offset=1": "calibre/newest_2.xml",
        "http://h/opds/navcatalog/4f617574686f7273": "calibre/authors.xml",
        "http://h/opds/category/617574686f7273/31": "calibre/author_jane.xml",
    }
    fetched = []

    def fetch(url):
        fetched.append(url)
        if url not in pages:
            raise IOError("404")
        return (FIXTURES / pages[url]).read_bytes()

    books = list(crawl("http://h/calibre/opds", fetch, source="test"))
    assert [b.title for b in books] == ["The Left Hand: A Novel", "CON"]
    assert all(b.source == "test" for b in books)
    assert "http://example.invalid/opds" not in fetched
    assert len(fetched) == len(set(fetched))
    assert "http://h/opds/broken" in fetched  # bad page is tried, logged, and skipped


CALIBRE_MULTI_ROOT = b"""<?xml version='1.0' encoding='utf-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>calibre Library</title>
  <id>urn:calibre:main</id>
  <link type="application/atom+xml;type=feed;profile=opds-catalog" rel="start" href="/opds?library_id=library"/>
  <entry>
    <title>By Newest</title>
    <id>calibre-navcatalog:1</id>
    <link type="application/atom+xml;type=feed;profile=opds-catalog" href="/opds/navcatalog/new?library_id=library"/>
  </entry>
  <entry>
    <title>Library: library</title>
    <id>calibre-library:library</id>
    <link type="application/atom+xml;type=feed;profile=opds-catalog" href="/opds?library_id=library"/>
  </entry>
  <entry>
    <title>Library: Second Library</title>
    <id>calibre-library:Second_Library</id>
    <link type="application/atom+xml;type=feed;profile=opds-catalog" href="/opds?library_id=Second_Library"/>
  </entry>
</feed>"""


def test_crawl_follows_every_calibre_library_once(caplog):
    import logging

    fetched = []

    def fetch(url):
        fetched.append(url)
        if url in ("http://h/opds", "http://h/opds?library_id=Second_Library"):
            return CALIBRE_MULTI_ROOT
        return (FIXTURES / "calibre/author_jane.xml").read_bytes()

    feed = parse_feed(CALIBRE_MULTI_ROOT, "http://h/opds")
    assert feed.libraries == [
        ("library", "http://h/opds?library_id=library"),
        ("Second Library", "http://h/opds?library_id=Second_Library"),
    ]
    with caplog.at_level(logging.INFO, logger="opds_mirror"):
        list(crawl("http://h/opds", fetch, source="c"))
    # The default library's own URL is the root under another name: not re-read.
    assert "http://h/opds?library_id=library" not in fetched
    assert "http://h/opds?library_id=Second_Library" in fetched
    assert "found library 'Second Library'" in caplog.text
    assert "found library 'library'" not in caplog.text


def test_find_catalog_root_adds_opds():
    from opds_mirror.opds import find_catalog_root

    def fetch(url):
        if url.split("?")[0] == "http://h:8080/opds":
            return CALIBRE_MULTI_ROOT
        return b"<html><body>Calibre web app</body></html>"

    assert find_catalog_root("http://h:8080/opds", fetch) == "http://h:8080/opds"
    assert find_catalog_root("http://h:8080", fetch) == "http://h:8080/opds"
    assert find_catalog_root("http://h:8080/", fetch) == "http://h:8080/opds"
    assert find_catalog_root("http://h:8080?library_id=x", fetch) == "http://h:8080/opds?library_id=x"
    import pytest

    with pytest.raises(Exception):
        find_catalog_root("http://other/", fetch)
