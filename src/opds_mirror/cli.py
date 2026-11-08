"""Command-line entry point: ``opds-mirror sync --config config.toml``."""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__
from .config import ConfigError, load_config
from .sync import Mirror


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opds-mirror", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--config", default="config.toml", help="path to the TOML config (default: config.toml)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log every request")
    parser.add_argument("-q", "--quiet", action="store_true", help="only log warnings and errors")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="download every new book from every configured server")
    sync.add_argument("-n", "--dry-run", action="store_true", help="list what would be downloaded without downloading")
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
        stats = Mirror(config, dry_run=args.dry_run).run()
        return 1 if stats.failed or stats.failed_servers else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
