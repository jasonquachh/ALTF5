"""Lever job board adapter.

Lever exposes a free, unauthenticated JSON API:

    https://api.lever.co/v0/postings/{company}?mode=json

`company` is the slug in jobs.lever.co/{company}.
"""

from __future__ import annotations

import logging
from typing import Iterator

from ..models import Internship
from ..parsing import (
    extract_deadline,
    extract_requirements,
    extract_salary,
    html_to_text,
    looks_like_internship,
    parse_timestamp,
    truncate,
)
from .base import Source

log = logging.getLogger(__name__)

API = "https://api.lever.co/v0/postings/{company}?mode=json"


class LeverSource(Source):
    type = "lever"

    def fetch(self) -> Iterator[Internship]:
        company_slug = self.cfg["token"]
        data = self._get_json(API.format(company=company_slug))
        for job in data:
            title = job.get("text", "")
            cats = job.get("categories", {}) or {}
            commitment = cats.get("commitment", "")
            desc = html_to_text(job.get("descriptionPlain") or job.get("description", ""))

            if not looks_like_internship(title, commitment, desc[:400]):
                continue

            locations = []
            if cats.get("location"):
                locations.append(cats["location"])
            for loc in cats.get("allLocations", []) or []:
                if loc not in locations:
                    locations.append(loc)

            # Lever "lists" hold the bullet sections (requirements, etc.).
            requirements = _requirements_from_lists(job.get("lists", [])) or \
                extract_requirements(desc)

            salary = None
            if job.get("salaryRange"):
                sr = job["salaryRange"]
                lo, hi = sr.get("min"), sr.get("max")
                cur = sr.get("currency", "")
                if lo and hi:
                    salary = f"{cur} {lo:,}–{hi:,}".strip()
            salary = salary or extract_salary(desc)

            yield Internship(
                source=self.type,
                external_id=str(job.get("id")),
                company=self.company,
                title=title,
                apply_url=job.get("hostedUrl") or job.get("applyUrl", ""),
                release_date=parse_timestamp(job.get("createdAt")),
                deadline=extract_deadline(desc),
                locations=locations or self.cfg.get("default_locations", []),
                salary=salary,
                requirements=requirements,
                department=cats.get("team") or cats.get("department"),
                employment_type=commitment or "Internship",
                remote=("remote" in (cats.get("location", "").lower())),
                description=truncate(desc, 600),
                raw=job,
            )


def _requirements_from_lists(lists, limit: int = 6) -> list[str]:
    for block in lists or []:
        text = (block.get("text") or "").lower()
        if any(k in text for k in ("requirement", "qualification", "looking for", "you have")):
            html = block.get("content", "")
            bullets = html_to_text(html).splitlines()
            out = [b.lstrip("•-*–— ").strip() for b in bullets if b.strip()]
            out = [truncate(b, 180) for b in out if len(b) >= 2]
            if out:
                return out[:limit]
    return []
