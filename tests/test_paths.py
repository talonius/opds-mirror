from pathlib import Path

from opds_mirror.paths import author_folder, book_dir, extension_for, safe_component


def test_safe_component_strips_bad_characters():
    assert safe_component('A Tale: Of Two/Three Cities?') == "A Tale_ Of Two_Three Cities_"
    assert safe_component("  trailing dots... ") == "trailing dots"
    assert safe_component("") == "Unknown"
    assert safe_component("CON") == "CON_"
    assert safe_component("x" * 300) == "x" * 120


def test_author_folder():
    assert author_folder(["Jane Doe", "John Roe"]) == "Jane Doe & John Roe"
    assert author_folder([]) == "Unknown Author"


def test_book_dir():
    assert book_dir(Path("/out"), ["Jane Doe"], "Book") == Path("/out/Jane Doe/Book")


def test_extension_for():
    assert extension_for("application/epub+zip", "http://h/x") == "epub"
    assert extension_for("application/octet-stream", "http://h/opds/download/3/azw3/") == "azw3"
    assert extension_for("", "http://h/get/mobi/2/Calibre_Library") == "mobi"
    assert extension_for("", "http://h/x", 'attachment; filename="Book - Author.kepub.epub"') == "kepub.epub"
    assert extension_for("", "http://h/x", "attachment; filename*=UTF-8''A%20B.fb2") == "fb2"
    assert extension_for("", "http://h/x") == "bin"
