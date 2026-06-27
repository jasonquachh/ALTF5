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

import logging
from dataclasses import dataclass

from .models import Internship
from .parsing import looks_closed

log = logging.getLogger(__name__)


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

        # Some ATSs return 200 with a "this job is closed" body.
        body = resp.text if "text/html" in resp.headers.get("Content-Type", "") else resp.text
        if looks_closed(body):
            return VerificationResult(False, "page reports posting closed", resp.status_code)

        return VerificationResult(True, "ok", resp.status_code)
