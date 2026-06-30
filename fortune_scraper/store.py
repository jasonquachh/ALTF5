"""SQLite-backed dedup store.

The store remembers every posting we have ever seen so that:

* a posting is announced to Discord exactly once ("find them as they release"),
* on the very first run we can optionally announce everything already open
  ("backfill"), and
* we can tell which previously-seen postings have since closed.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Internship

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS internships (
    uid           TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    company       TEXT NOT NULL,
    title         TEXT NOT NULL,
    apply_url     TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    pushed_at     TEXT,
    closed_at     TEXT,
    payload       TEXT
);
CREATE INDEX IF NOT EXISTS idx_company ON internships(company);
CREATE INDEX IF NOT EXISTS idx_pushed ON internships(pushed_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str = "internships.db") -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        with closing(self.conn.cursor()) as cur:
            cur.executescript(_SCHEMA)
        self.conn.commit()

    # -- queries ------------------------------------------------------------

    def is_known(self, uid: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM internships WHERE uid=?", (uid,))
        return cur.fetchone() is not None

    def is_pushed(self, uid: str) -> bool:
        cur = self.conn.execute(
            "SELECT pushed_at FROM internships WHERE uid=?", (uid,)
        )
        row = cur.fetchone()
        return bool(row and row["pushed_at"])

    def open_uids(self) -> set[str]:
        cur = self.conn.execute(
            "SELECT uid FROM internships WHERE closed_at IS NULL"
        )
        return {r["uid"] for r in cur.fetchall()}

    def open_uids_for_companies(self, companies: set[str]) -> set[str]:
        """Open postings belonging to the given companies (by name)."""
        if not companies:
            return set()
        cur = self.conn.execute(
            "SELECT uid, company FROM internships WHERE closed_at IS NULL"
        )
        return {r["uid"] for r in cur.fetchall() if r["company"] in companies}

    def records(self, *, only_open: bool = True, only_unpushed: bool = False) -> list[dict]:
        """Return stored postings as dicts (from the saved JSON payload),
        most-recently-seen first. Used for the spreadsheet/CSV export."""
        sql = "SELECT payload, pushed_at, closed_at, last_seen FROM internships"
        clauses = []
        if only_open:
            clauses.append("closed_at IS NULL")
        if only_unpushed:
            clauses.append("pushed_at IS NULL")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY last_seen DESC"
        out = []
        for row in self.conn.execute(sql).fetchall():
            try:
                rec = json.loads(row["payload"]) if row["payload"] else {}
            except (ValueError, TypeError):
                rec = {}
            rec["pushed"] = bool(row["pushed_at"])
            out.append(rec)
        return out

    # -- mutations ----------------------------------------------------------

    def upsert_seen(self, item: Internship) -> bool:
        """Record that we just saw `item`. Returns True if it is brand new."""
        now = _now()
        is_new = not self.is_known(item.uid)
        payload = json.dumps(item.to_record())
        if is_new:
            self.conn.execute(
                """INSERT INTO internships
                   (uid, source, external_id, company, title, apply_url,
                    first_seen, last_seen, payload)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    item.uid, item.source, item.external_id, item.company,
                    item.title, item.apply_url, now, now, payload,
                ),
            )
        else:
            # Re-seen: refresh last_seen and clear any stale closed flag.
            self.conn.execute(
                """UPDATE internships
                   SET last_seen=?, payload=?, closed_at=NULL
                   WHERE uid=?""",
                (now, payload, item.uid),
            )
        self.conn.commit()
        return is_new

    def mark_pushed(self, uid: str) -> None:
        self.conn.execute(
            "UPDATE internships SET pushed_at=? WHERE uid=?", (_now(), uid)
        )
        self.conn.commit()

    def mark_closed(self, uids) -> int:
        now = _now()
        uids = list(uids)
        if not uids:
            return 0
        self.conn.executemany(
            "UPDATE internships SET closed_at=? WHERE uid=? AND closed_at IS NULL",
            [(now, u) for u in uids],
        )
        self.conn.commit()
        return len(uids)

    def stats(self) -> dict:
        cur = self.conn.execute(
            """SELECT
                 COUNT(*) AS total,
                 SUM(CASE WHEN pushed_at IS NOT NULL THEN 1 ELSE 0 END) AS pushed,
                 SUM(CASE WHEN closed_at IS NULL THEN 1 ELSE 0 END) AS open
               FROM internships"""
        )
        row = cur.fetchone()
        return {k: (row[k] or 0) for k in ("total", "pushed", "open")}

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
