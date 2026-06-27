#!/usr/bin/env python3
"""Convenience entrypoint so you can run `python main.py run`."""

from fortune_scraper.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
