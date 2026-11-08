"""Command-line entry point: ``opds-mirror sync --config config.toml``."""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .config import ConfigError, load_config
from .index import BookIndex
from .sync import Mirror, refresh_index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opds-mirror", description="Mirror books from OPDS catalogs.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--config", default="config.toml", help="path to the TOML config (default: config.toml)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log every request")
    parser.add_argument("-q", "--quiet", action="store_true", help="only log warnings and errors")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="download every new book from every configured server")
    sync.add_argument("-n", "--dry-run", action="store_true", help="list what would be downloaded without downloading")
    sync.add_argument(
        "--recheck",
        action="store_true",
        help="re-examine links handled on earlier runs (e.g. after removing books from your library)",
    )

    sub.add_parser("index", help="scan the library folders and the mirror, and update the duplicate index")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    level = logging.DEBUG if args.verbose else logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")
    if not args.verbose:
        logging.getLogger("urllib3").setLevel(logging.WARNING)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "sync":
        stats = Mirror(config, dry_run=args.dry_run, recheck=args.recheck).run()
        return 1 if stats.failed or stats.failed_servers else 0
    if args.command == "index":
        index = BookIndex(config.index_file)
        try:
            refresh_index(config, index)
        finally:
            index.close()
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
