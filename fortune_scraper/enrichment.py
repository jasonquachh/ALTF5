"""Fill in missing posting details by digging into the real application page.

Aggregator feeds (json_list) often carry only title/company/location/URL. Before
announcing such a posting we fetch its actual job page — via the ATS's structured
API when the apply URL points at Greenhouse / Lever / Ashby, or the raw page
otherwise — and extract a concise description, requirements, salary, deadline and
location. This guarantees every announced posting carries enough information to
decide whether it's worth applying, instead of a half-empty card.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse

from .models import Internship
from .parsing import (
    extract_deadline,
    extract_requirements,
    extract_salary,
    html_to_text,
    summarize,
)

log = logging.getLogger(__name__)


def needs_enrichment(item: Internship) -> bool:
    """True if the posting is missing fields a reader needs to judge it."""
    return not (item.description and item.requirements and item.salary)


def enrich(item: Internship, http) -> None:
    """Best-effort, in-place enrichment. Never raises."""
    if not needs_enrichment(item):
        return
    url = item.apply_url or ""
    host = (urlparse(url).hostname or "").lower()
    try:
        if "greenhouse.io" in host:
            _from_greenhouse(item, http, url)
        elif "lever.co" in host:
            _from_lever(item, http, url)
        elif "ashbyhq.com" in host:
            _from_ashby(item, http, url)
        else:
            _from_generic(item, http, url)
    except Exception as exc:  # enrichment is best-effort
        log.debug("enrichment failed for %s: %s", url, exc)


# ---------------------------------------------------------------------------

def _apply_text(item: Internship, text: str) -> None:
    if not text:
        return
    if not item.description:
        item.description = summarize(text, 360)
    if not item.requirements:
        item.requirements = extract_requirements(text)
    if not item.salary:
        item.salary = extract_salary(text)
    if not item.deadline:
        item.deadline = extract_deadline(text)


def _from_greenhouse(item, http, url) -> None:
    board, jid = _parse_greenhouse(url)
    if not board or not jid:
        return _from_generic(item, http, url)
    api = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{jid}"
    data = _get_json(http, api)
    _apply_text(item, html_to_text(data.get("content", "")))
    loc = (data.get("location") or {}).get("name")
    if loc and not item.locations:
        item.locations = [loc]


def _parse_greenhouse(url):
    p = urlparse(url)
    q = parse_qs(p.query)
    if "for" in q and "token" in q:          # embed/job_app?for=BOARD&token=ID
        return q["for"][0], q["token"][0]
    m = re.search(r"/([^/]+)/jobs/(\d+)", p.path)
    if m:
        return m.group(1), m.group(2)
    return None, None


def _from_lever(item, http, url) -> None:
    p = urlparse(url)
    m = re.search(r"/([^/]+)/([0-9a-fA-F-]{36})", p.path)
    if not m:
        return _from_generic(item, http, url)
    data = _get_json(http, f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}")
    desc = html_to_text(data.get("descriptionPlain") or data.get("description", ""))
    _apply_text(item, desc)
    reqs = _lever_lists(data.get("lists", []))
    if reqs and not item.requirements:
        item.requirements = reqs
    cats = data.get("categories", {}) or {}
    if cats.get("location") and not item.locations:
        item.locations = [cats["location"]]


def _lever_lists(lists):
    for block in lists or []:
        text = (block.get("text") or "").lower()
        if any(k in text for k in ("requirement", "qualification", "looking for")):
            bullets = html_to_text(block.get("content", "")).splitlines()
            out = [b.lstrip("•-*–— ").strip() for b in bullets if b.strip()]
            out = [b for b in out if len(b) >= 2]
            if out:
                return out[:6]
    return []


def _from_ashby(item, http, url) -> None:
    parts = [x for x in urlparse(url).path.split("/") if x]
    if len(parts) < 2:
        return
    org, jid = parts[0], parts[1]
    data = _get_json(
        http, f"https://api.ashbyhq.com/posting-api/job-board/{org}?includeCompensation=true"
    )
    for job in data.get("jobs", []):
        if str(job.get("id")) == jid:
            _apply_text(item, html_to_text(job.get("descriptionHtml")
                                           or job.get("descriptionPlain", "")))
            comp = job.get("compensation") or {}
            if not item.salary and comp.get("compensationTierSummary"):
                item.salary = str(comp["compensationTierSummary"])
            if job.get("location") and not item.locations:
                item.locations = [job["location"]]
            return


def _from_generic(item, http, url) -> None:
    resp = http.get(url, allow_redirects=True)
    if getattr(resp, "status_code", 200) >= 400:
        return
    # If the link redirected to a known ATS, use its structured API instead of
    # scraping the noisy HTML.
    final = getattr(resp, "url", "") or url
    fhost = (urlparse(final).hostname or "").lower()
    if final != url:
        if "greenhouse.io" in fhost:
            return _from_greenhouse(item, http, final)
        if "lever.co" in fhost:
            return _from_lever(item, http, final)
        if "ashbyhq.com" in fhost:
            return _from_ashby(item, http, final)
    # Generic pages are noisy, so we only trust regex-extractable comp/deadline.
    text = html_to_text(getattr(resp, "text", "") or "")
    if not item.salary:
        item.salary = extract_salary(text)
    if not item.deadline:
        item.deadline = extract_deadline(text)


def _get_json(http, url):
    resp = http.get(url)
    resp.raise_for_status()
    return resp.json()
