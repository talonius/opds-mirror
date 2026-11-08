"""A tiny fake OPDS server that serves Calibre- and Calibre-Web-style feeds."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
ATOM = "application/atom+xml;profile=opds-catalog"


def book_bytes(name: str) -> bytes:
    return f"fake book contents: {name}\n".encode() * 50


# path (with query) -> (body, content type, extra headers)
ROUTES: dict[str, tuple[bytes, str, dict[str, str]]] = {
    # Calibre content server
    "/calibre/opds": ((FIXTURES / "calibre/root.xml").read_bytes(), ATOM, {}),
    "/opds/navcatalog/4f6e6577657374": ((FIXTURES / "calibre/newest.xml").read_bytes(), ATOM, {}),
    "/opds/navcatalog/4f6e6577657374?offset=1": ((FIXTURES / "calibre/newest_2.xml").read_bytes(), ATOM, {}),
    "/opds/navcatalog/4f617574686f7273": ((FIXTURES / "calibre/authors.xml").read_bytes(), ATOM, {}),
    "/opds/category/617574686f7273/31": ((FIXTURES / "calibre/author_jane.xml").read_bytes(), ATOM, {}),
    "/opds/broken": (b"<html>not a feed</html>", "text/html", {}),
    "/get/epub/1/Calibre_Library": (
        book_bytes("left hand epub"), "application/epub+zip",
        {"Content-Disposition": 'attachment; filename="The Left Hand_ A Novel - Jane Doe.epub"'},
    ),
    "/get/pdf/1/Calibre_Library": (book_bytes("left hand pdf"), "application/pdf", {}),
    "/get/mobi/2/Calibre_Library": (book_bytes("con mobi"), "application/x-mobipocket-ebook", {}),
    # Calibre-Web
    "/cw/opds": ((FIXTURES / "calibreweb/root.xml").read_bytes(), ATOM, {}),
    "/opds/books": ((FIXTURES / "calibreweb/books.xml").read_bytes(), ATOM, {}),
    "/opds/books/letter/a": ((FIXTURES / "calibreweb/letter_a.xml").read_bytes(), ATOM, {}),
    "/opds/books/letter/a?offset=60": ((FIXTURES / "calibreweb/letter_a_60.xml").read_bytes(), ATOM, {}),
    "/opds/discover": ((FIXTURES / "calibreweb/discover.xml").read_bytes(), ATOM, {}),
    "/opds/download/3/epub/": (
        book_bytes("tale epub"), "application/epub+zip",
        {"Content-Disposition": "attachment; filename*=UTF-8''A%20Tale%20-%20Charles%20Dickens.epub"},
    ),
    "/opds/download/3/azw3/": (book_bytes("tale azw3"), "application/octet-stream", {}),
    "/opds/download/4/pdf/": (book_bytes("anon pdf"), "application/pdf", {}),
}


class Handler(BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self):  # noqa: N802
        Handler.hits.append(self.path)
        route = ROUTES.get(self.path)
        if route is None:
            self.send_response(404)
            self.end_headers()
            return
        body, ctype, extra = route
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def opds_server():
    Handler.hits = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", Handler
    finally:
        server.shutdown()
        server.server_close()
