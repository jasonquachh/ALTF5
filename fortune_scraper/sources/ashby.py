"""Ashby job board adapter.

Ashby exposes a public posting API:

    https://api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true

`name` is the job-board slug in jobs.ashbyhq.com/{name}.
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

API = "https://api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true"


class AshbySource(Source):
    type = "ashby"

    def fetch(self) -> Iterator[Internship]:
        name = self.cfg["token"]
        data = self._get_json(API.format(name=name))
        for job in data.get("jobs", []):
            title = job.get("title", "")
            etype = job.get("employmentType", "") or ""
            desc = html_to_text(job.get("descriptionHtml") or job.get("descriptionPlain", ""))

            if not looks_like_internship(title, etype, desc[:400]):
                continue

            locations = []
            if job.get("location"):
                locations.append(job["location"])
            for sec in job.get("secondaryLocations", []) or []:
                loc = sec.get("location") if isinstance(sec, dict) else sec
                if loc and loc not in locations:
                    locations.append(loc)

            salary = _compensation(job) or extract_salary(desc)

            yield Internship(
                source=self.type,
                external_id=str(job.get("id")),
                company=self.company,
                title=title,
                apply_url=job.get("applyUrl") or job.get("jobUrl", ""),
                release_date=parse_timestamp(job.get("publishedAt") or job.get("updatedAt")),
                deadline=extract_deadline(desc),
                locations=locations or self.cfg.get("default_locations", []),
                salary=salary,
                requirements=extract_requirements(desc),
                department=job.get("department") or job.get("team"),
                employment_type=etype or "Internship",
                remote=bool(job.get("isRemote")),
                description=truncate(desc, 600),
                raw=job,
            )


def _compensation(job: dict):
    comp = job.get("compensation") or {}
    summary = comp.get("compensationTierSummary") or comp.get("summary")
    if summary:
        return str(summary)
    tiers = comp.get("compensationTiers") or []
    if tiers and isinstance(tiers, list):
        first = tiers[0]
        if isinstance(first, dict) and first.get("title"):
            return str(first["title"])
    return None
