"""Push internship announcements to Discord via an incoming webhook.

Each internship becomes a rich embed showing the fields the user asked for:
release date, deadline, requirements, locations, salary, and a verified apply
link. Embeds are batched (Discord allows up to 10 per message) and the webhook
rate limit is respected via the Retry-After header.
"""

from __future__ import annotations

import logging
import time

from .models import Internship
from .parsing import summarize

log = logging.getLogger(__name__)

EMBED_LIMIT = 10            # Discord hard limit: max embeds per webhook message
MAX_MESSAGE_CHARS = 5500   # Discord rejects a message whose embeds total > 6000
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
    if item.category:
        fields.append(_field("🗂️ Category", item.category.title()))
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
    description = summarize(item.description, 400)

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

    def announce(self, items: list[tuple[Internship, bool]]) -> list[Internship]:
        """Send announcements. `items` is a list of (internship, is_new).

        Embeds are packed into messages that stay under both Discord's 10-embed
        and ~6000-character-per-message limits. Returns the list of internships
        that were actually delivered, so the caller marks exactly those as
        pushed (a partially-failed batch must not mark the wrong ones).
        """
        # Pre-render each embed once and measure it.
        rendered = [(it, build_embed(it, is_new)) for it, is_new in items]

        delivered: list[Internship] = []
        batch: list[tuple[Internship, dict]] = []
        batch_chars = 0

        def flush() -> None:
            nonlocal batch, batch_chars
            if not batch:
                return
            if self._send([e for _, e in batch]):
                delivered.extend(it for it, _ in batch)
            batch = []
            batch_chars = 0

        for it, embed in rendered:
            size = _embed_size(embed)
            if batch and (len(batch) >= EMBED_LIMIT or batch_chars + size > MAX_MESSAGE_CHARS):
                flush()
            batch.append((it, embed))
            batch_chars += size
        flush()
        return delivered

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


def _embed_size(embed: dict) -> int:
    """Approximate the character count Discord charges an embed against the
    6000-per-message limit (title + description + every field + footer)."""
    n = len(embed.get("title") or "") + len(embed.get("description") or "")
    for f in embed.get("fields", []):
        n += len(f.get("name", "")) + len(f.get("value", ""))
    n += len((embed.get("footer") or {}).get("text", ""))
    return n
