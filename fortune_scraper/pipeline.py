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
from .parsing import (
    categorize,
    clean_salary,
    filter_us_locations,
    is_graduate_only,
    looks_unpaid,
)
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
        # One notifier per category webhook (plus a default/catch-all). When a
        # category has no dedicated webhook it falls back to the default.
        self._notifiers: dict[str, DiscordNotifier] = {}
        for category in ("healthcare", "engineering", "tech", "business"):
            url = settings.webhook_for(category)
            self._notifiers[category] = DiscordNotifier(
                url, self.http, username=settings.discord_username,
                dry_run=settings.dry_run,
            )
        # Back-compat default notifier (used when a posting has no category).
        self.notifier = DiscordNotifier(
            settings.discord_webhook_url, self.http,
            username=settings.discord_username, dry_run=settings.dry_run,
        )

    def _notifier_for(self, category: str) -> DiscordNotifier:
        return self._notifiers.get(category, self.notifier)

    def run_once(self) -> dict:
        s = self.settings
        seen_uids: set[str] = set()
        scanned_companies: set[str] = set()
        to_announce: list[tuple[Internship, bool]] = []
        queued_by_cat: dict[str, int] = {}
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
                # Intra-run dedup: never process the same posting twice in one
                # pass (some feeds list a job under multiple locations).
                if item.uid in seen_uids:
                    continue
                seen_uids.add(item.uid)
                scanned += 1

                # US-only filter: drop non-US roles and trim foreign offices
                # off the locations we display.
                if s.us_only:
                    is_us, us_locs = filter_us_locations(item.locations)
                    if not is_us:
                        log.info("Skipping non-US role: %s %s", item, item.locations)
                        continue
                    item.locations = us_locs

                # College focus: de-emphasize PhD / master's / MBA / postdoc
                # roles so the feed targets college-level students.
                if s.college_focus and is_graduate_only(item.title):
                    log.info("Skipping graduate-only role: %s", item)
                    continue

                # Paid-only: drop roles that explicitly state they are unpaid /
                # for academic credit. (Anything with listed comp is kept.)
                if s.exclude_unpaid and not item.salary and looks_unpaid(item.description):
                    log.info("Skipping unpaid role: %s", item)
                    continue

                # Clean up display fields before anything is stored or sent:
                # validate the salary so only sensible comp is shown, and sort
                # the role into a category/channel.
                item.salary = clean_salary(item.salary)
                item.category = categorize(item.title, item.department, item.description)
                # A company-level category hint (e.g. healthcare/biotech firms)
                # routes otherwise-generic roles to that channel; clear role
                # signals (engineering/business/etc.) still win.
                hint = company.get("category")
                if hint and item.category == "tech":
                    item.category = hint

                is_new = self.store.upsert_seen(item)
                already_pushed = self.store.is_pushed(item.uid)
                if already_pushed:
                    continue

                # Drip throttle: cap how many postings we announce (0 = unlimited).
                # A per-category cap (one per channel) takes precedence when set;
                # otherwise the global per-run cap applies. Everything is still
                # scanned above so dedup/closed-tracking stay accurate — we just
                # stop *announcing* once the cap is hit; the rest carry over.
                if s.max_announce_per_category:
                    if queued_by_cat.get(item.category, 0) >= s.max_announce_per_category:
                        continue
                elif s.max_announce_per_run and len(to_announce) >= s.max_announce_per_run:
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
                queued_by_cat[item.category] = queued_by_cat.get(item.category, 0) + 1
                if decision == "backfill":
                    backfill_used += 1

            polite_sleep(s.request_delay_seconds)

        # Anything we knew was open but didn't see this pass is likely closed.
        # Scoped to companies we actually scanned so a transient fetch failure
        # never marks a whole company's postings closed by mistake.
        closed = self._reconcile_closed(seen_uids, scanned_companies)

        sent = 0
        by_category: dict[str, int] = {}
        if to_announce:
            # Oldest-released first so each channel reads chronologically.
            to_announce.sort(
                key=lambda t: t[0].release_date or datetime.min.replace(tzinfo=timezone.utc)
            )
            # Group by category and announce each group to its own channel.
            groups: dict[str, list] = {}
            for item, is_new in to_announce:
                groups.setdefault(item.category or "tech", []).append((item, is_new))

            for category, items in groups.items():
                notifier = self._notifier_for(category)
                delivered = notifier.announce(items)
                # Only persist "pushed" for postings Discord actually accepted.
                # Dry-run logs what *would* be sent but must not mark pushed.
                if not notifier.dry_run:
                    for item in delivered:
                        self.store.mark_pushed(item.uid)
                sent += len(delivered)
                if delivered:
                    by_category[category] = len(delivered)

        summary = {
            "companies": len(s.companies),
            "scanned": scanned,
            "announced": sent,
            "announced_by_category": by_category,
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
