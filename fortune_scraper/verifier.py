"""Verify that an internship is genuinely open and applyable.

The user explicitly asked that we "verify that the internship is actually
applyable" before announcing it. We do three cheap checks:

1. There is a usable application URL.
2. That URL responds successfully (2xx, following redirects).
3. The returned page does not contain obvious "closed / filled / no longer
   accepting applications" markers.

Sources whose listing endpoint only ever returns *currently open* postings
(Greenhouse, Lever, Ashby, Workday all do) already give us a strong signal,
so a verification failure is treated as "skip for now", not "permanently
dead" — we simply don't push it this cycle and retry next time.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .models import Internship
from .parsing import looks_closed, looks_scam

log = logging.getLogger(__name__)

# Hosts we treat as high-confidence legitimate (known ATS / job platforms).
_REPUTABLE_HOST_RE = re.compile(
    r"(^|\.)("
    r"greenhouse\.io|boards\.greenhouse\.io|lever\.co|ashbyhq\.com|"
    r"myworkdayjobs\.com|icims\.com|smartrecruiters\.com|workable\.com|"
    r"jobvite\.com|taleo\.net|successfactors\.com|oraclecloud\.com|"
    r"wd1\.myworkdaysite\.com|simplify\.jobs|linkedin\.com|indeed\.com|"
    r"ziprecruiter\.com|paylocity\.com|bamboohr\.com|breezy\.hr|"
    r"applytojob\.com|recruitee\.com|teamtailor\.com|eightfold\.ai|"
    r"avature\.net|gh\.io|join\.com)$",
    re.IGNORECASE,
)


@dataclass
class VerificationResult:
    ok: bool
    reason: str
    status_code: int | None = None


class Verifier:
    def __init__(self, http, enabled: bool = True) -> None:
        self.http = http
        self.enabled = enabled

    def verify(self, item: Internship) -> VerificationResult:
        if not item.apply_url or not item.apply_url.startswith(("http://", "https://")):
            return VerificationResult(False, "missing or invalid apply URL")

        # Legitimacy: reject bare-IP hosts outright (classic scam/phishing tell).
        host = (urlparse(item.apply_url).hostname or "").lower()
        if _is_ip(host):
            return VerificationResult(False, "suspicious apply host (raw IP)")

        if not self.enabled:
            return VerificationResult(True, "verification disabled")

        try:
            resp = self.http.get(item.apply_url, allow_redirects=True)
        except Exception as exc:
            return VerificationResult(False, f"request failed: {exc}")

        if resp.status_code == 404 or resp.status_code == 410:
            return VerificationResult(False, "posting not found (gone)", resp.status_code)
        if resp.status_code >= 400:
            return VerificationResult(
                False, f"unexpected status {resp.status_code}", resp.status_code
            )

        body = resp.text or ""

        # Legitimacy: reject pages showing recruitment-scam signals.
        if looks_scam(body):
            return VerificationResult(False, "page shows scam signals", resp.status_code)

        # Some ATSs return 200 with a "this job is closed" body.
        if looks_closed(body):
            return VerificationResult(False, "page reports posting closed", resp.status_code)

        # Where the request actually landed (after redirects).
        final_host = (urlparse(getattr(resp, "url", "") or item.apply_url).hostname or "").lower()
        if _is_ip(final_host):
            return VerificationResult(False, "redirects to raw IP host", resp.status_code)

        reputable = bool(_REPUTABLE_HOST_RE.search(final_host or host))
        reason = "ok (reputable ATS)" if reputable else "ok"
        return VerificationResult(True, reason, resp.status_code)


def _is_ip(host: str) -> bool:
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False
