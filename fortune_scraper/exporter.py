"""Export the on-file programs to a spreadsheet (CSV) for separate viewing."""

from __future__ import annotations

import csv
from pathlib import Path

from .store import Store

# Columns chosen for a recruiter-friendly spreadsheet view.
_COLUMNS = [
    ("category", "Category"),
    ("company", "Company"),
    ("title", "Title"),
    ("primary_location", "Location"),
    ("salary", "Salary"),
    ("release_date", "Released"),
    ("deadline", "Deadline"),
    ("employment_type", "Type"),
    ("source", "Source"),
    ("apply_url", "Apply URL"),
    ("requirements", "Requirements"),
    ("pushed", "Already Pushed"),
]


def _location(rec: dict) -> str:
    locs = rec.get("locations") or []
    if not locs:
        return "Remote" if rec.get("remote") else "Not specified"
    head = locs[0]
    return f"{head} (+{len(locs) - 1} more)" if len(locs) > 1 else head


def _cell(rec: dict, key: str) -> str:
    if key == "primary_location":
        return _location(rec)
    val = rec.get(key)
    if val is None:
        return ""
    if isinstance(val, list):
        return " | ".join(str(v) for v in val)
    if isinstance(val, bool):
        return "yes" if val else "no"
    return str(val)


def export_csv(store: Store, path: str, *, only_open: bool = True,
               only_unpushed: bool = False) -> int:
    """Write matching postings to `path` as CSV. Returns the row count."""
    rows = store.records(only_open=only_open, only_unpushed=only_unpushed)
    # Sort by category then company for a tidy spreadsheet.
    rows.sort(key=lambda r: (r.get("category") or "zz", r.get("company") or ""))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([header for _, header in _COLUMNS])
        for rec in rows:
            writer.writerow([_cell(rec, key) for key, _ in _COLUMNS])
    return len(rows)
