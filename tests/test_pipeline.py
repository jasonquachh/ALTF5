import os

from fortune_scraper.config import Settings
from fortune_scraper.models import Internship
from fortune_scraper.pipeline import Pipeline
from fortune_scraper.store import Store
from tests.conftest import FakeHTTP, FakeResponse


def _greenhouse_payload(job_id, title="Software Intern, Summer 2025"):
    return {
        "jobs": [
            {
                "id": job_id,
                "title": title,
                "absolute_url": f"https://boards.greenhouse.io/acme/jobs/{job_id}",
                "first_published": "2025-01-05T00:00:00Z",
                "location": {"name": "Remote"},
                "content": "<p>Great internship. Apply now, we are hiring!</p>",
            }
        ]
    }


def _settings(tmp_path):
    return Settings(
        companies=[{"name": "Acme", "type": "greenhouse", "token": "acme"}],
        discord_webhook_url="https://discord.test/api/webhooks/1/abc",
        db_path=str(tmp_path / "test.db"),
        verify_applyable=True,
        announce_backfill=True,
        dry_run=False,           # exercise the real delivery path (mocked HTTP)
    )


def _patch_http(pipe, payload):
    fake = FakeHTTP(
        {
            "boards-api.greenhouse.io": FakeResponse(payload),
            # The verifier GETs the apply URL; return an "open" page for it.
            "boards.greenhouse.io/acme/jobs": FakeResponse(
                text="<html>Apply now! We are hiring.</html>",
                headers={"Content-Type": "text/html"},
            ),
            # The Discord webhook POST: 204 = delivered.
            "discord.test": FakeResponse(status_code=204),
        }
    )
    pipe.http = fake
    pipe.verifier.http = fake
    pipe.notifier.http = fake
    pipe.notifier.dry_run = False


def test_announces_once_then_dedupes(tmp_path):
    settings = _settings(tmp_path)
    pipe = Pipeline(settings)
    _patch_http(pipe, _greenhouse_payload(1))

    first = pipe.run_once()
    assert first["announced"] == 1
    assert first["scanned"] == 1

    # Second pass over the same posting: already pushed -> nothing announced.
    second = pipe.run_once()
    assert second["announced"] == 0
    pipe.close()


def test_dry_run_does_not_mark_pushed(tmp_path):
    # Regression: a dry run must not record postings as pushed, otherwise they
    # are silently swallowed once a real webhook is configured.
    settings = _settings(tmp_path)
    pipe = Pipeline(settings)
    _patch_http(pipe, _greenhouse_payload(1))
    pipe.notifier.dry_run = True

    r1 = pipe.run_once()
    assert r1["announced"] == 1            # dry-run still logs what it would send
    assert pipe.store.stats()["pushed"] == 0   # but nothing is marked pushed

    # Configure a real webhook: the posting now actually goes out.
    pipe.notifier.dry_run = False
    r2 = pipe.run_once()
    assert r2["announced"] == 1
    assert pipe.store.stats()["pushed"] == 1
    pipe.close()


def test_new_posting_detected_on_later_pass(tmp_path):
    settings = _settings(tmp_path)
    pipe = Pipeline(settings)

    _patch_http(pipe, _greenhouse_payload(1))
    pipe.run_once()

    # A brand-new job appears in the feed.
    _patch_http(pipe, _greenhouse_payload(2, "Data Intern, Summer 2025"))
    result = pipe.run_once()
    assert result["announced"] == 1
    pipe.close()


def test_unverifiable_posting_is_skipped(tmp_path):
    settings = _settings(tmp_path)
    pipe = Pipeline(settings)
    payload = _greenhouse_payload(9)
    fake = FakeHTTP(
        {
            "boards-api.greenhouse.io": FakeResponse(payload),
            # Apply page says the role is closed -> must NOT be announced.
            "boards.greenhouse.io/acme/jobs": FakeResponse(
                text="<html>This position has been filled.</html>",
                headers={"Content-Type": "text/html"},
                status_code=200,
            ),
        }
    )
    pipe.http = fake
    pipe.verifier.http = fake
    pipe.notifier.http = fake

    result = pipe.run_once()
    assert result["announced"] == 0
    pipe.close()


def test_store_marks_closed_when_posting_disappears(tmp_path):
    settings = _settings(tmp_path)
    pipe = Pipeline(settings)

    _patch_http(pipe, _greenhouse_payload(1))
    pipe.run_once()
    assert pipe.store.stats()["open"] == 1

    # Posting gone from the feed -> reconciled as closed.
    _patch_http(pipe, {"jobs": []})
    pipe.run_once()
    assert pipe.store.stats()["open"] == 0
    pipe.close()
