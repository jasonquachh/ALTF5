"""Workday adapter.

Workday is the most common ATS among Fortune 500 companies. It exposes an
unofficial-but-stable "CXS" JSON endpoint that powers the public career site:

    POST https://{host}/wday/cxs/{tenant}/{site}/jobs
         body: {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "intern"}

A per-posting detail document (with the full description, comp, dates) lives at:

    GET  https://{host}/wday/cxs/{tenant}/{site}{externalPath}

Config block::

    - name: Example Corp
      type: workday
      host: example.wd5.myworkdayjobs.com
      tenant: example
      site: External
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

_PAGE = 20
_MAX_PAGES = 10  # safety cap: up to 200 matching postings per company


class WorkdaySource(Source):
    type = "workday"

    def fetch(self) -> Iterator[Internship]:
        host = self.cfg["host"].rstrip("/")
        tenant = self.cfg["tenant"]
        site = self.cfg["site"]
        fetch_detail = self.cfg.get("fetch_detail", True)

        list_url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        offset = 0
        for _ in range(_MAX_PAGES):
            payload = {
                "appliedFacets": {},
                "limit": _PAGE,
                "offset": offset,
                "searchText": self.cfg.get("search_text", "intern"),
            }
            data = self._post_json(list_url, json=payload)
            postings = data.get("jobPostings", [])
            if not postings:
                break

            for jp in postings:
                title = jp.get("title", "")
                if not looks_like_internship(title):
                    continue

                external_path = jp.get("externalPath", "")
                public_url = f"https://{host}/{site}{external_path}"
                locations_text = jp.get("locationsText", "")
                locations = [locations_text] if locations_text else []

                internship = Internship(
                    source=self.type,
                    external_id=external_path or jp.get("bulletFields", [""])[0],
                    company=self.company,
                    title=title,
                    apply_url=public_url,
                    release_date=parse_timestamp(jp.get("startDate")),
                    locations=locations or self.cfg.get("default_locations", []),
                    employment_type="Internship",
                    raw=jp,
                )

                if fetch_detail and external_path:
                    try:
                        self._enrich(internship, host, tenant, site, external_path)
                    except Exception as exc:  # detail is best-effort
                        log.debug("Workday detail fetch failed for %s: %s", title, exc)

                yield internship

            offset += _PAGE
            if offset >= data.get("total", 0):
                break

    def _enrich(self, internship: Internship, host, tenant, site, external_path) -> None:
        detail_url = f"https://{host}/wday/cxs/{tenant}/{site}{external_path}"
        data = self._get_json(detail_url)
        info = data.get("jobPostingInfo", {}) or {}

        desc = html_to_text(info.get("jobDescription", ""))
        internship.description = truncate(desc, 600)
        internship.requirements = extract_requirements(desc)
        internship.deadline = extract_deadline(desc) or parse_timestamp(info.get("endDate"))
        internship.release_date = internship.release_date or parse_timestamp(
            info.get("startDate") or info.get("postedOn")
        )

        # Locations
        locs = []
        if info.get("location"):
            locs.append(info["location"])
        for al in info.get("additionalLocations", []) or []:
            if al and al not in locs:
                locs.append(al)
        if locs:
            internship.locations = locs

        # Compensation
        salary = None
        for field_name in ("payRange", "compensation", "salaryRange"):
            val = info.get(field_name)
            if isinstance(val, str) and val.strip():
                salary = val.strip()
                break
        internship.salary = salary or extract_salary(desc)
        internship.remote = bool(info.get("remoteType")) or None
