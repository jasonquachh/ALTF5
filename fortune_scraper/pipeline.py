"""The orchestration layer that ties every component together.

Flow for a single pass:

    for each company:
        fetch live internship postings (source adapter)
        for each posting:
            record "seen" in the store (detect brand-new vs already-known)
            decide whether it should be announced:
                * brand new  -> announce (these are the "just opened" ones)
                * already open but never pushed, and backfill is on -> announce
            verify it is actually applyable before announcing
    detect postings that disappeared from every feed -> mark closed
    push the chosen announcements to Discord (batched)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .config import Settings
from .discord_notifier import DiscordNotifier
from .http_client import build_session, polite_sleep
from .models import Internship
from .sources import build_source
from .store import Store
from .verifier import Verifier

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = build_session(timeout=20.0)
        self.store = Store(settings.db_path)
        self.verifier = Verifier(self.http, enabled=settings.verify_applyable)
        self.notifier = DiscordNotifier(
            settings.discord_webhook_url,
            self.http,
            username=settings.discord_username,
            dry_run=settings.dry_run,
        )

    def run_once(self) -> dict:
        s = self.settings
        seen_uids: set[str] = set()
        scanned_companies: set[str] = set()
        to_announce: list[tuple[Internship, bool]] = []
        backfill_used = 0
        errors: list[str] = []
        scanned = 0

        for company in s.companies:
            name = company.get("name", company.get("token", "?"))
            try:
                source = build_source(company, self.http)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                log.error("Skipping %s: %s", name, exc)
                continue

            try:
                postings = list(source.fetch())
            except Exception as exc:
                errors.append(f"{name}: fetch failed: {exc}")
                log.warning("Fetch failed for %s: %s", name, exc)
                polite_sleep(s.request_delay_seconds)
                continue

            scanned_companies.add(source.company)
            for item in postings:
                scanned += 1
                seen_uids.add(item.uid)
                is_new = self.store.upsert_seen(item)
                already_pushed = self.store.is_pushed(item.uid)
                if already_pushed:
                    continue

                if not self._within_recency(item):
                    continue

                if is_new:
                    decision = "new"
                elif s.announce_backfill and backfill_used < s.max_backfill_per_run:
                    decision = "backfill"
                else:
                    continue

                result = self.verifier.verify(item)
                if not result.ok:
                    log.info("Not applyable, skipping: %s (%s)", item, result.reason)
                    continue

                to_announce.append((item, is_new))
                if decision == "backfill":
                    backfill_used += 1

            polite_sleep(s.request_delay_seconds)

        # Anything we knew was open but didn't see this pass is likely closed.
        # Scoped to companies we actually scanned so a transient fetch failure
        # never marks a whole company's postings closed by mistake.
        closed = self._reconcile_closed(seen_uids, scanned_companies)

        sent = 0
        if to_announce:
            # Oldest-released first so the channel reads chronologically.
            to_announce.sort(
                key=lambda t: t[0].release_date or datetime.min.replace(tzinfo=timezone.utc)
            )
            delivered = self.notifier.announce(to_announce)
            sent = len(delivered)
            # Only persist "pushed" for the postings Discord actually accepted.
            # In dry-run we log what *would* be sent but must NOT mark it pushed,
            # otherwise the posting is silently swallowed once a real webhook is
            # configured.
            if not self.notifier.dry_run:
                for item in delivered:
                    self.store.mark_pushed(item.uid)

        summary = {
            "companies": len(s.companies),
            "scanned": scanned,
            "announced": sent,
            "queued": len(to_announce),
            "backfilled": backfill_used,
            "closed": closed,
            "errors": errors,
            "store": self.store.stats(),
        }
        log.info("Run complete: %s", summary)
        return summary

    def _within_recency(self, item: Internship) -> bool:
        days = self.settings.only_new_since_days
        if not days or not item.release_date:
            return True
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return item.release_date >= cutoff

    def _reconcile_closed(self, seen_uids: set[str], scanned_companies: set[str]) -> int:
        if not scanned_companies:
            return 0
        previously_open = self.store.open_uids_for_companies(scanned_companies)
        gone = previously_open - seen_uids
        return self.store.mark_closed(gone)

    def close(self) -> None:
        self.store.close()
