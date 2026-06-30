"""Command-line entrypoint.

Usage:
    python -m fortune_scraper.cli run            # one pass, then exit
    python -m fortune_scraper.cli watch --interval 900   # loop forever
    python -m fortune_scraper.cli stats          # show store stats
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from .config import load_settings
from .pipeline import Pipeline


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def _print_summary(summary: dict) -> None:
    print("\n=== Run summary ===")
    print(f"  Companies scanned : {summary['companies']}")
    print(f"  Postings scanned  : {summary['scanned']}")
    print(f"  Announced to Discord: {summary['announced']}")
    print(f"  Backfilled        : {summary['backfilled']}")
    print(f"  Marked closed     : {summary['closed']}")
    store = summary["store"]
    print(f"  Store: {store['total']} total, {store['open']} open, {store['pushed']} pushed")
    if summary["errors"]:
        print(f"  Errors ({len(summary['errors'])}):")
        for e in summary["errors"][:20]:
            print(f"    - {e}")
    print("===================\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="fortune-scraper",
        description="Scrape Fortune 500 internships and announce them to Discord.",
    )
    # Common flags accepted both before and after the subcommand. Defaults are
    # set only on the top-level parser; the subparser copies use SUPPRESS so an
    # unspecified flag never clobbers a value given before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true",
                        default=argparse.SUPPRESS)
    common.add_argument("--config", default=argparse.SUPPRESS)
    common.add_argument("--companies", default=argparse.SUPPRESS)
    common.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS,
                        help="Scrape and log announcements without posting to Discord.")

    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--companies", default="data/companies.yaml")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scrape and log announcements without posting to Discord.")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", parents=[common], help="Run a single scrape pass and exit.")
    watch = sub.add_parser("watch", parents=[common], help="Run continuously on an interval.")
    watch.add_argument("--interval", type=int, default=900,
                       help="Seconds between passes (default 900 = 15 min).")
    sub.add_parser("stats", parents=[common], help="Print dedup-store statistics and exit.")
    exp = sub.add_parser("export", parents=[common],
                         help="Export on-file programs to a CSV spreadsheet.")
    exp.add_argument("--output", default="queued_programs.csv",
                     help="CSV path to write (default queued_programs.csv).")
    exp.add_argument("--all", action="store_true",
                     help="Include already-pushed programs too (default: unpushed only).")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    settings = load_settings(args.config, args.companies)
    if args.dry_run:
        settings.dry_run = True

    if not settings.companies:
        print("No companies configured. Add entries to data/companies.yaml.", file=sys.stderr)
        return 2

    command = args.command or "run"

    # Only the announce paths need a webhook; export/stats just read the store.
    if command in ("run", "watch") and not settings.has_webhook and not settings.dry_run:
        print(
            "Warning: no Discord webhook is set — running in dry-run mode.",
            file=sys.stderr,
        )
        settings.dry_run = True

    if command == "stats":
        pipe = Pipeline(settings)
        print(pipe.store.stats())
        pipe.close()
        return 0

    if command == "export":
        from .exporter import export_csv
        from .store import Store
        store = Store(settings.db_path)
        try:
            count = export_csv(
                store, args.output, only_open=True, only_unpushed=not args.all
            )
        finally:
            store.close()
        scope = "all open" if args.all else "queued (not yet pushed)"
        print(f"Exported {count} {scope} programs to {args.output}")
        return 0

    if command == "run":
        pipe = Pipeline(settings)
        try:
            summary = pipe.run_once()
            _print_summary(summary)
        finally:
            pipe.close()
        return 0

    if command == "watch":
        interval = args.interval
        print(f"Watching {len(settings.companies)} companies every {interval}s. Ctrl-C to stop.")
        pipe = Pipeline(settings)
        try:
            while True:
                try:
                    summary = pipe.run_once()
                    _print_summary(summary)
                except Exception:
                    logging.exception("Pass failed; will retry next interval.")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            pipe.close()
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
