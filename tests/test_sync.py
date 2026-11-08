from opds_mirror.config import Config, ServerConfig, load_config
from opds_mirror.http import Client
from opds_mirror.sync import Mirror


def make_config(base, tmp_path):
    return Config(
        output_dir=tmp_path / "out",
        servers=[
            ServerConfig(url=f"{base}/calibre/opds", name="calibre"),
            ServerConfig(url=f"{base}/cw/opds", name="calibre-web"),
        ],
    )


def tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and ".opds-mirror" not in p.parts)


def test_sync_downloads_every_format_from_every_server(opds_server, tmp_path):
    base, _ = opds_server
    config = make_config(base, tmp_path)
    stats = Mirror(config).run()

    assert tree(config.output_dir) == [
        "Ann Other/CON_/CON_.mobi",
        "Charles Dickens/A Tale_ Of Two_Three Cities_/A Tale_ Of Two_Three Cities_.azw3",
        "Charles Dickens/A Tale_ Of Two_Three Cities_/A Tale_ Of Two_Three Cities_.epub",
        "Jane Doe & John Roe/The Left Hand_ A Novel/The Left Hand_ A Novel.epub",
        "Jane Doe & John Roe/The Left Hand_ A Novel/The Left Hand_ A Novel.pdf",
        "Unknown Author/Anonymous Work/Anonymous Work.pdf",
    ]
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
    assert stats.skipped_existing == 6
    assert not [h for h in handler.hits if "/get/" in h or "/download/" in h]


def test_dry_run_writes_nothing(opds_server, tmp_path):
    base, _ = opds_server
    config = make_config(base, tmp_path)
    stats = Mirror(config, dry_run=True).run()
    assert stats.would_download == 6
    assert not config.output_dir.exists()


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
    assert [s.name for s in config.servers] == ["http://a/opds", "b"]
