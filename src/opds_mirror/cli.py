"""Command-line entry point: ``opds-mirror sync --config config.toml``."""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__
from .config import ConfigError, load_config
from .index import BookIndex
from .lock import AlreadyRunning, RunLock
from .sync import Mirror, refresh_index

log = logging.getLogger("opds_mirror")

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opds-mirror", description="Mirror books from OPDS catalogs.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--config", default="config.toml", help="path to the TOML config (default: config.toml)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log every request")
    parser.add_argument("-q", "--quiet", action="store_true", help="only print warnings and errors (good for cron)")
    parser.add_argument("--log-file", help="also write a full log here (overrides log_file in the config)")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="download every new book from every configured server")
    sync.add_argument("-n", "--dry-run", action="store_true", help="list what would be downloaded without downloading")
    sync.add_argument(
        "--recheck",
        action="store_true",
        help="re-examine links handled on earlier runs (e.g. after removing books from your library)",
    )
    sync.add_argument(
        "-k",
        "--insecure",
        action="store_true",
        help="don't check TLS certificates on any server (same as verify_ssl = false everywhere)",
    )

    sub.add_parser("index", help="scan the library folders and the mirror, and update the duplicate index")
    return parser


def setup_logging(verbose: bool, quiet: bool, log_file: Path | None) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO)
    console.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(console)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fh.setLevel(logging.DEBUG if verbose else logging.INFO)
        fh.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(fh)
    if not verbose:
        logging.getLogger("urllib3").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    log_file = Path(args.log_file).expanduser() if args.log_file else config.log_file
    setup_logging(args.verbose, args.quiet, log_file)

    try:
        with RunLock(config.lock_file):
            if args.command == "sync":
                if args.insecure:
                    for server in config.servers:
                        server.verify_ssl = False
                stats = Mirror(config, dry_run=args.dry_run, recheck=args.recheck).run()
                if stats.failed or stats.failed_servers:
                    log.warning("finished with problems: %s", stats.summary())
                    return 1
                return 0
            if args.command == "index":
                index = BookIndex(config.index_file)
                try:
                    refresh_index(config, index)
                finally:
                    index.close()
                return 0
    except AlreadyRunning as exc:
        # An earlier cron run is still going; that's normal for a long first sync.
        log.info("%s; exiting", exc)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
