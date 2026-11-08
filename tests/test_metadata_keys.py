from pathlib import Path

from opds_mirror.keys import isbn13, normalize_authors, normalize_title, title_key
from opds_mirror.metadata import metadata_from_path, read_metadata

FILES = Path(__file__).parent / "fixtures" / "files"


def test_isbn13():
    assert isbn13("0-306-40615-2") == "9780306406157"
    assert isbn13("978-0-306-40615-7") == "9780306406157"
    assert isbn13("0306406153") is None  # bad check digit
    assert isbn13("9780306406158") is None
    assert isbn13("080442957X") == "9780804429573"


def test_normalized_keys():
    assert normalize_title("The Left Hand of Darkness!") == "left hand of darkness"
    assert normalize_title("Café") == "cafe"
    assert normalize_authors(["Doe, Jane & John Roe"]) == normalize_authors(["John Roe", "Jane Doe"])
    assert title_key(["Jane Doe"], "The Book") == title_key(["DOE, JANE"], "Book")
    assert title_key([], "Book") is None
    assert title_key(["Unknown"], "Book") is None


def test_read_epub_made_by_calibre():
    meta = read_metadata(FILES / "tiny.epub", "epub")
    assert meta.title == "Epub Title"
    assert meta.authors == ["Doe, Jane", "John Roe"]
    assert meta.isbns == ["9780306406157"]


def test_read_mobi_and_azw3_made_by_calibre():
    for name, fmt in [("tiny.mobi", "mobi"), ("tiny.azw3", "azw3")]:
        meta = read_metadata(FILES / name, fmt)
        assert meta.title == "Mobi Title"
        assert meta.authors == ["Mo Author"]
        assert meta.isbns == ["9780306406157"]


def test_unreadable_file_gives_empty_metadata(tmp_path):
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"not a zip")
    assert read_metadata(bad, "epub").title == ""
    assert read_metadata(bad, "txt").title == ""


def test_metadata_from_calibre_style_path():
    meta = metadata_from_path(Path("/lib/Jane Doe/The Book (123)/The Book - Jane Doe.epub"))
    assert meta.title == "The Book"
    assert meta.authors == ["Jane Doe"]
