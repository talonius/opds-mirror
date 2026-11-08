import shutil
from pathlib import Path

from conftest import book_bytes

from opds_mirror.config import Config, ServerConfig, load_config
from opds_mirror.http import Client
from opds_mirror.sync import Mirror

FILES = Path(__file__).parent / "fixtures" / "files"

ALL_FILES = [
    "Ann Other/CON_/CON_.mobi",
    "Charles Dickens/A Tale_ Of Two_Three Cities_/A Tale_ Of Two_Three Cities_.azw3",
    "Charles Dickens/A Tale_ Of Two_Three Cities_/A Tale_ Of Two_Three Cities_.epub",
    "Jane Doe & John Roe/The Left Hand_ A Novel/The Left Hand_ A Novel.epub",
    "Jane Doe & John Roe/The Left Hand_ A Novel/The Left Hand_ A Novel.pdf",
    "Unknown Author/Anonymous Work/Anonymous Work.pdf",
]


def make_config(base, tmp_path, library=None):
    return Config(
        output_dir=tmp_path / "out",
        servers=[
            ServerConfig(url=f"{base}/calibre/opds", name="calibre"),
            ServerConfig(url=f"{base}/cw/opds", name="calibre-web"),
        ],
        library_dirs=[library] if library else [],
    )


def tree(root):
    return sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".opds-mirror" not in p.parts
    )


def downloads(handler):
    return [h for h in handler.hits if "/get/" in h or "/download/" in h]


def test_sync_downloads_every_format_from_every_server(opds_server, tmp_path):
    base, _ = opds_server
    config = make_config(base, tmp_path)
    stats = Mirror(config).run()

    assert tree(config.output_dir) == ALL_FILES
    assert stats.books == 4
    assert stats.downloaded == 6
    assert stats.failed == 0
    assert not list((config.output_dir / ".opds-mirror" / "tmp").iterdir())


def test_second_run_downloads_nothing(opds_server, tmp_path):
    base, handler = opds_server
    config = make_config(base, tmp_path)
    Mirror(config).run()
    handler.hits.clear()

    stats = Mirror(config).run()
    assert stats.downloaded == 0
    assert stats.skipped_known == 6
    assert not downloads(handler)

    # --recheck ignores the remote cache, but the files are already there.
    stats = Mirror(config, recheck=True).run()
    assert stats.skipped_existing == 6
    assert not downloads(handler)


def test_dry_run_writes_nothing(opds_server, tmp_path):
    base, _ = opds_server
    config = make_config(base, tmp_path)
    stats = Mirror(config, dry_run=True).run()
    assert stats.would_download == 6
    assert not config.output_dir.exists()


def test_isbn_match_in_library_skips_that_format_only(opds_server, tmp_path):
    base, handler = opds_server
    library = tmp_path / "library"
    library.mkdir()
    # Same ISBN as "The Left Hand" in the Calibre feed, but EPUB only.
    shutil.copy(FILES / "tiny.epub", library / "something.epub")
    config = make_config(base, tmp_path, library)

    stats = Mirror(config).run()
    assert stats.skipped_duplicate == 1
    assert "/get/epub/1/Calibre_Library" not in downloads(handler)  # never downloaded
    files = tree(config.output_dir)
    assert "Jane Doe & John Roe/The Left Hand_ A Novel/The Left Hand_ A Novel.epub" not in files
    assert "Jane Doe & John Roe/The Left Hand_ A Novel/The Left Hand_ A Novel.pdf" in files


def test_author_title_match_in_library_from_folder_names(opds_server, tmp_path):
    base, _ = opds_server
    library = tmp_path / "library"
    # Calibre library layout; the file has no readable metadata.
    book = library / "Dickens, Charles" / "A Tale - Of Two Three Cities (12)" / "x.epub"
    book.parent.mkdir(parents=True)
    book.write_bytes(b"not really an epub")
    config = make_config(base, tmp_path, library)

    stats = Mirror(config).run()
    assert stats.skipped_duplicate == 1
    files = tree(config.output_dir)
    assert not any(f.endswith("Cities_.epub") for f in files)
    assert any(f.endswith("Cities_.azw3") for f in files)


def test_hash_match_is_discarded_after_download_and_not_fetched_again(opds_server, tmp_path):
    base, handler = opds_server
    library = tmp_path / "library"
    library.mkdir()
    (library / "renamed.txt").write_bytes(book_bytes("anon pdf"))  # same bytes, any name
    config = make_config(base, tmp_path, library)

    stats = Mirror(config).run()
    assert stats.discarded_duplicate == 1
    assert "Unknown Author/Anonymous Work/Anonymous Work.pdf" not in tree(config.output_dir)

    handler.hits.clear()
    stats = Mirror(config).run()
    assert stats.downloaded == 0
    assert not downloads(handler)


SECOND_SERVER_FEED = b"""<?xml version='1.0' encoding='utf-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>second</id><title>Second server</title>
  <entry>
    <title>The Left Hand: a novel</title>
    <author><name>Roe, John</name></author>
    <author><name>Jane Doe</name></author>
    <id>urn:uuid:different-id-on-this-server</id>
    <link type="application/epub+zip" href="/second/get/epub/9" rel="http://opds-spec.org/acquisition"/>
    <link type="application/x-mobipocket-ebook" href="/second/get/mobi/9" rel="http://opds-spec.org/acquisition"/>
  </entry>
</feed>"""


def test_same_book_on_another_server_only_adds_new_formats(opds_server, tmp_path, monkeypatch):
    import conftest

    base, handler = opds_server
    monkeypatch.setitem(conftest.ROUTES, "/second/opds", (SECOND_SERVER_FEED, conftest.ATOM, {}))
    monkeypatch.setitem(conftest.ROUTES, "/second/get/mobi/9", (book_bytes("left hand mobi"), "application/x-mobipocket-ebook", {}))
    monkeypatch.setitem(conftest.ROUTES, "/second/get/epub/9", (book_bytes("other epub"), "application/epub+zip", {}))
    config = make_config(base, tmp_path)
    config.servers.append(ServerConfig(url=f"{base}/second/opds", name="second"))

    stats = Mirror(config).run()
    assert stats.skipped_existing == 1  # the EPUB is already in the same folder
    assert "/second/get/epub/9" not in downloads(handler)
    # The MOBI is new, and goes next to the EPUB and PDF from the first server.
    assert tree(config.output_dir) == sorted(
        ALL_FILES + ["Jane Doe & John Roe/The Left Hand_ A Novel/The Left Hand_ A Novel.mobi"]
    )


def test_unreachable_server_is_reported_and_others_continue(opds_server, tmp_path):
    base, _ = opds_server
    config = make_config(base, tmp_path)
    config.servers.insert(0, ServerConfig(url="http://127.0.0.1:1/opds", name="down"))
    stats = Mirror(config, client=Client("test", timeout=5, retries=0)).run()
    assert stats.failed_servers == ["down"]
    assert stats.downloaded == 6


def test_load_config(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'output_dir = "books"\nlibrary_dirs = ["lib"]\n'
        '[[servers]]\nurl = "http://a/opds"\n[[servers]]\nname = "b"\nurl = "http://b/opds"\n'
    )
    config = load_config(cfg)
    assert config.output_dir == (tmp_path / "books").resolve()
    assert config.library_dirs == [(tmp_path / "lib").resolve()]
    assert config.index_file == config.output_dir / ".opds-mirror" / "index.sqlite"
    assert [s.name for s in config.servers] == ["http://a/opds", "b"]


def test_progress_lines_are_logged(opds_server, tmp_path, caplog, monkeypatch):
    import logging

    import opds_mirror.progress as progress

    monkeypatch.setattr(progress.Ticker, "due", lambda self: True)  # report on every step
    base, _ = opds_server
    library = tmp_path / "library"
    library.mkdir()
    shutil.copy(FILES / "tiny.epub", library / "a.epub")
    config = make_config(base, tmp_path, library)
    with caplog.at_level(logging.INFO, logger="opds_mirror"):
        Mirror(config).run()
    text = caplog.text
    assert "scanning" in text and "for the first time" in text
    assert "books checked" in text
    assert "catalog pages read" in text and "still queued" in text
    assert "downloading 'CON' (mobi) from calibre" in text
    assert "still downloading" in text
    assert "saved Ann Other/CON_/CON_.mobi" in text
