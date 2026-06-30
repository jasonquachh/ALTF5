from fortune_scraper.sources.json_list import JsonListSource
from fortune_scraper.verifier import Verifier
from fortune_scraper.models import Internship
from tests.conftest import FakeHTTP, FakeResponse


def test_parses_simplify_style_listings():
    payload = [
        {
            "id": "abc123", "title": "Software Engineer Intern",
            "company_name": "Acme", "locations": ["New York, NY"],
            "url": "https://job-boards.greenhouse.io/acme/jobs/1",
            "date_posted": 1736467200, "active": True, "is_visible": True,
        },
        {  # inactive -> skipped
            "id": "def456", "title": "Data Intern", "company_name": "Beta",
            "url": "https://example.com/2", "active": False, "is_visible": True,
        },
        {  # missing url -> skipped
            "id": "ghi", "title": "Product Intern", "company_name": "Gamma",
        },
    ]
    http = FakeHTTP({"listings.json": FakeResponse(payload)})
    src = JsonListSource(
        {"name": "Feed", "type": "json_list", "source_label": "intern-list",
         "url": "https://x/listings.json"}, http)
    items = list(src.fetch())

    assert len(items) == 1
    it = items[0]
    assert it.source == "intern-list"
    assert it.company == "Acme"
    assert it.external_id == "abc123"
    assert it.title == "Software Engineer Intern"
    assert it.locations == ["New York, NY"]
    assert it.release_date is not None


def test_parses_object_wrapped_listings():
    payload = {"listings": [
        {"role": "Marketing Intern", "company": "Delta",
         "apply_url": "https://jobs.lever.co/delta/1", "active": True},
    ]}
    http = FakeHTTP({"feed": FakeResponse(payload)})
    src = JsonListSource(
        {"name": "Feed", "type": "json_list", "url": "https://x/feed"}, http)
    items = list(src.fetch())
    assert len(items) == 1
    assert items[0].title == "Marketing Intern"
    assert items[0].company == "Delta"


def _intern(url):
    return Internship(source="x", external_id="1", company="Acme",
                      title="Intern", apply_url=url)


def test_verifier_rejects_ip_host():
    http = FakeHTTP({})
    v = Verifier(http, enabled=True)
    res = v.verify(_intern("http://203.0.113.5/apply"))
    assert not res.ok and "IP" in res.reason


def test_verifier_rejects_scam_page():
    http = FakeHTTP({"sketchy.example": FakeResponse(
        text="<html>To apply send a $200 training fee via wire transfer</html>",
        headers={"Content-Type": "text/html"})})
    v = Verifier(http, enabled=True)
    res = v.verify(_intern("https://sketchy.example/job"))
    assert not res.ok and "scam" in res.reason


def test_verifier_passes_reputable():
    http = FakeHTTP({"greenhouse.io": FakeResponse(
        text="<html>Apply now, we are hiring!</html>",
        headers={"Content-Type": "text/html"})})
    v = Verifier(http, enabled=True)
    res = v.verify(_intern("https://boards.greenhouse.io/acme/jobs/1"))
    assert res.ok
