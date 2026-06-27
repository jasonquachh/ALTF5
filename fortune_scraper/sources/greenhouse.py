"""Greenhouse job board adapter.

Greenhouse exposes a free, unauthenticated JSON API:

    https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true

`token` is the board slug, e.g. the `stripe` in boards.greenhouse.io/stripe.
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

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


class GreenhouseSource(Source):
    type = "greenhouse"

    def fetch(self) -> Iterator[Internship]:
        token = self.cfg["token"]
        data = self._get_json(API.format(token=token))
        for job in data.get("jobs", []):
            title = job.get("title", "")
            content = html_to_text(job.get("content", ""))
            # Detect on the title only — the description body often mentions
            # "interns" in boilerplate and would cause false positives.
            if not looks_like_internship(title):
                continue

            locations = []
            loc = (job.get("location") or {}).get("name")
            if loc:
                locations = [loc]
            for office in job.get("offices", []) or []:
                if office.get("name") and office["name"] not in locations:
                    locations.append(office["name"])

            salary = extract_salary(content)
            # Greenhouse pay metadata, when present, is more reliable.
            for meta in job.get("metadata", []) or []:
                name = (meta.get("name") or "").lower()
                if "pay" in name or "salary" in name or "compensation" in name:
                    if meta.get("value"):
                        salary = str(meta["value"])
                        break

            yield Internship(
                source=self.type,
                external_id=str(job.get("id")),
                company=self.company,
                title=title,
                apply_url=job.get("absolute_url", ""),
                release_date=parse_timestamp(
                    job.get("first_published") or job.get("updated_at")
                ),
                deadline=extract_deadline(content),
                locations=locations or self.cfg.get("default_locations", []),
                salary=salary,
                requirements=extract_requirements(content),
                employment_type="Internship",
                description=truncate(content, 600),
                raw=job,
            )
