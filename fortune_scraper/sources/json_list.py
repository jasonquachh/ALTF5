"""Adapter for JSON internship feeds (aggregators / open-source listing repos).

Sites like intern-list.com aggregate their data from open, structured internship
lists (e.g. the Simplify / Pitt CSC `listings.json` files on GitHub). This
adapter reads such a feed — a JSON array, or an object containing a list under a
common key — and maps each entry into a normalized Internship. It is deliberately
tolerant of field-name differences across feeds.

Config block::

    - name: Summer 2026 Internships (Simplify)
      type: json_list
      url: https://raw.githubusercontent.com/<owner>/<repo>/<branch>/.github/scripts/listings.json
      source_label: intern-list          # used for stable dedup ids
"""

from __future__ import annotations

import hashlib
import logging
from typing import Iterator, Optional

from ..models import Internship
from ..parsing import html_to_text, parse_timestamp, truncate
from .base import Source

log = logging.getLogger(__name__)

_LIST_KEYS = ("listings", "jobs", "internships", "data", "results", "items", "postings")


def _first(entry: dict, *keys: str) -> Optional[str]:
    for k in keys:
        v = entry.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _truthy(entry: dict, key: str, default: bool = True) -> bool:
    v = entry.get(key, default)
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "no", "0", "")
    return bool(v)


class JsonListSource(Source):
    type = "json_list"

    def fetch(self) -> Iterator[Internship]:
        url = self.cfg["url"]
        label = self.cfg.get("source_label", "intern-list")
        data = self._get_json(url)

        if isinstance(data, dict):
            for key in _LIST_KEYS:
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            log.warning("%s: unexpected JSON shape from %s", label, url)
            return

        for entry in data:
            if not isinstance(entry, dict):
                continue

            # Respect active/visible flags so we don't surface dead listings.
            if not _truthy(entry, "active", True) or not _truthy(entry, "is_visible", True):
                continue
            if not _truthy(entry, "visible", True):
                continue

            title = _first(entry, "title", "role", "position", "name", "job_title")
            apply_url = _first(
                entry, "url", "apply_url", "application_url", "applicationUrl",
                "link", "apply_link", "href", "job_url",
            )
            if not title or not apply_url:
                continue

            company = _first(
                entry, "company_name", "company", "employer", "organization",
                "companyName", "org",
            ) or "Unknown"

            locations = entry.get("locations")
            if isinstance(locations, str):
                locations = [locations]
            if not locations:
                loc = _first(entry, "location", "city", "office")
                locations = [loc] if loc else []

            release = parse_timestamp(
                entry.get("date_posted") or entry.get("date_updated")
                or entry.get("posted_at") or entry.get("created_at") or entry.get("date")
            )

            ext = _first(entry, "id", "slug", "uuid") or _hash(apply_url)
            desc = _first(entry, "description", "summary", "details")

            yield Internship(
                source=label,
                external_id=str(ext),
                company=company,
                title=title,
                apply_url=apply_url,
                release_date=release,
                locations=locations or self.cfg.get("default_locations", []),
                employment_type="Internship",
                description=truncate(html_to_text(desc), 600) if desc else None,
                raw=entry,
            )


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
