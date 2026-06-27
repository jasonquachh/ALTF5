"""Push internship announcements to Discord via an incoming webhook.

Each internship becomes a rich embed showing the fields the user asked for:
release date, deadline, requirements, locations, salary, and a verified apply
link. Embeds are batched (Discord allows up to 10 per message) and the webhook
rate limit is respected via the Retry-After header.
"""

from __future__ import annotations

import logging
import time
from typing import Iterable

from .models import Internship

log = logging.getLogger(__name__)

EMBED_LIMIT = 10            # Discord max embeds per webhook message
COLOR_NEW = 0x2ECC71       # green – freshly opened
COLOR_OPEN = 0x3498DB      # blue  – already open (backfill)


def _fmt_date(dt) -> str:
    if not dt:
        return "Not specified"
    # Discord renders <t:unix:D> as a localized date for every viewer.
    try:
        return f"<t:{int(dt.timestamp())}:D>"
    except Exception:
        return dt.strftime("%Y-%m-%d")


def _field(name: str, value: str, inline: bool = True) -> dict:
    value = (value or "Not specified").strip() or "Not specified"
    return {"name": name[:256], "value": value[:1024], "inline": inline}


def build_embed(item: Internship, is_new: bool) -> dict:
    fields = [
        _field("📍 Location", item.primary_location),
        _field("💰 Salary", item.salary or "Not listed"),
        _field("📅 Released", _fmt_date(item.release_date)),
        _field("⏰ Deadline", _fmt_date(item.deadline)),
    ]
    if item.department:
        fields.append(_field("🏢 Team", item.department))
    if item.employment_type:
        fields.append(_field("🧾 Type", item.employment_type))

    if item.requirements:
        reqs = "\n".join(f"• {r}" for r in item.requirements[:6])
        fields.append(_field("✅ Requirements", reqs, inline=False))

    if item.locations and len(item.locations) > 1:
        fields.append(
            _field("🌐 All locations", ", ".join(item.locations[:8]), inline=False)
        )

    tag = "🆕 Just opened" if is_new else "📌 Open now"
    description = item.description or ""
    if len(description) > 400:
        description = description[:399] + "…"

    return {
        "title": f"{item.title}"[:256],
        "url": item.apply_url or None,
        "description": f"**{item.company}** — {tag}\n\n{description}".strip()[:4096],
        "color": COLOR_NEW if is_new else COLOR_OPEN,
        "fields": fields,
        "footer": {"text": f"{item.company} • via {item.source} • Apply now ↗"},
    }


class DiscordNotifier:
    def __init__(self, webhook_url: str, http, username: str = "Internship Radar",
                 dry_run: bool = False) -> None:
        self.webhook_url = webhook_url
        self.http = http
        self.username = username
        self.dry_run = dry_run or not webhook_url

    def announce(self, items: list[tuple[Internship, bool]]) -> int:
        """Send announcements. `items` is a list of (internship, is_new).

        Returns the number successfully delivered.
        """
        sent = 0
        for batch in _chunk(items, EMBED_LIMIT):
            embeds = [build_embed(it, is_new) for it, is_new in batch]
            if self._send(embeds):
                sent += len(batch)
        return sent

    def _send(self, embeds: list[dict]) -> bool:
        payload = {"username": self.username, "embeds": embeds}
        if self.dry_run:
            for e in embeds:
                log.info("[dry-run] would announce: %s", e["title"])
            return True

        for attempt in range(5):
            resp = self.http.post(self.webhook_url, json=payload)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "1"))
                log.warning("Discord rate limited; sleeping %.1fs", retry_after)
                time.sleep(retry_after + 0.25)
                continue
            if resp.status_code in (200, 204):
                return True
            log.error(
                "Discord webhook failed (%s): %s", resp.status_code, resp.text[:300]
            )
            return False
        return False


def _chunk(seq: list, size: int) -> Iterable[list]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
