from fortune_scraper import discord_notifier
from fortune_scraper.discord_notifier import DiscordNotifier, build_embed, _embed_size
from fortune_scraper.models import Internship
from tests.conftest import FakeResponse


def _intern(i, desc=""):
    return Internship(
        source="greenhouse", external_id=str(i), company=f"Co{i}",
        title=f"Intern {i}", apply_url=f"https://x/{i}", description=desc,
    )


class _SeqHTTP:
    """Returns queued responses in order, recording each posted payload."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.payloads = []

    def post(self, url, json=None, **kwargs):
        self.payloads.append(json)
        return self._responses.pop(0) if self._responses else FakeResponse(status_code=204)


def test_returns_only_delivered_items_on_partial_failure(monkeypatch):
    # Force one embed per message so each item is its own request.
    monkeypatch.setattr(discord_notifier, "EMBED_LIMIT", 1)
    http = _SeqHTTP([
        FakeResponse(status_code=400, text="too big"),  # item 1 rejected
        FakeResponse(status_code=204),                   # item 2 ok
        FakeResponse(status_code=204),                   # item 3 ok
    ])
    notifier = DiscordNotifier("https://discord.test/hook", http)
    items = [(_intern(1), True), (_intern(2), True), (_intern(3), True)]

    delivered = notifier.announce(items)

    # The rejected first item must NOT be reported as delivered.
    assert [d.external_id for d in delivered] == ["2", "3"]
    assert len(http.payloads) == 3


def _big_intern(i):
    # Large but realistic embed: long requirements + many locations.
    it = _intern(i, desc="d" * 500)
    it.requirements = ["R" * 170 for _ in range(6)]
    it.locations = ["City " + "L" * 100 for _ in range(8)]
    return it


def test_packs_under_char_limit():
    # Each big embed is ~2.5k chars, so only ~2 fit under the 5500/msg cap.
    http = _SeqHTTP([FakeResponse(status_code=204) for _ in range(10)])
    notifier = DiscordNotifier("https://discord.test/hook", http)
    items = [(_big_intern(i), True) for i in range(5)]

    delivered = notifier.announce(items)

    assert len(delivered) == 5
    # 5 large embeds cannot fit in one message -> the notifier splits them.
    assert len(http.payloads) >= 2
    for payload in http.payloads:
        total = sum(_embed_size(e) for e in payload["embeds"])
        assert total <= discord_notifier.MAX_MESSAGE_CHARS or len(payload["embeds"]) == 1


def test_dry_run_reports_all_delivered():
    notifier = DiscordNotifier("", None, dry_run=True)
    items = [(_intern(1), True), (_intern(2), False)]
    delivered = notifier.announce(items)
    assert len(delivered) == 2
