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
