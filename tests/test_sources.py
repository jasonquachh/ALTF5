from fortune_scraper.sources.greenhouse import GreenhouseSource
from fortune_scraper.sources.lever import LeverSource
from fortune_scraper.sources.ashby import AshbySource
from fortune_scraper.sources.workday import WorkdaySource
from tests.conftest import FakeHTTP, FakeResponse


def test_greenhouse_filters_and_maps():
    payload = {
        "jobs": [
            {
                "id": 1,
                "title": "Software Engineering Intern, Summer 2025",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                "updated_at": "2025-01-10T00:00:00Z",
                "first_published": "2025-01-05T00:00:00Z",
                "location": {"name": "New York, NY"},
                "offices": [{"name": "New York, NY"}, {"name": "Remote - US"}],
                "content": "<p>Join us</p><h3>Requirements</h3><ul>"
                           "<li>Pursuing a CS degree</li><li>Knows Python</li></ul>"
                           "<p>Compensation: $45 - $55 per hour</p>",
                "metadata": [],
            },
            {
                "id": 2,
                "title": "Staff Engineer",  # not an internship -> filtered out
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
                "content": "<p>Senior role</p>",
            },
        ]
    }
    http = FakeHTTP({"boards-api.greenhouse.io": FakeResponse(payload)})
    src = GreenhouseSource({"name": "Acme", "type": "greenhouse", "token": "acme"}, http)
    items = list(src.fetch())

    assert len(items) == 1
    it = items[0]
    assert it.company == "Acme"
    assert it.external_id == "1"
    assert "New York, NY" in it.locations
    assert "Remote - US" in it.locations
    assert it.salary == "$45 - $55"
    assert any("Python" in r for r in it.requirements)
    assert it.release_date.year == 2025
    assert it.apply_url.endswith("/jobs/1")


def test_lever_maps_lists_and_salary_range():
    payload = [
        {
            "id": "abc",
            "text": "Data Science Internship",
            "hostedUrl": "https://jobs.lever.co/acme/abc",
            "createdAt": 1736467200000,
            "categories": {
                "location": "San Francisco, CA",
                "commitment": "Intern",
                "team": "Data",
                "allLocations": ["San Francisco, CA", "Remote"],
            },
            "descriptionPlain": "Work with data.",
            "lists": [
                {
                    "text": "Requirements",
                    "content": "<ul><li>Stats coursework</li><li>SQL</li></ul>",
                }
            ],
            "salaryRange": {"min": 8000, "max": 9000, "currency": "USD"},
        },
        {
            "id": "def",
            "text": "VP of Sales",  # filtered
            "categories": {"commitment": "Full-time"},
            "descriptionPlain": "Lead sales.",
        },
    ]
    http = FakeHTTP({"api.lever.co": FakeResponse(payload)})
    src = LeverSource({"name": "Acme", "type": "lever", "token": "acme"}, http)
    items = list(src.fetch())

    assert len(items) == 1
    it = items[0]
    assert it.department == "Data"
    assert "Remote" in it.locations
    assert "8,000" in it.salary and "9,000" in it.salary
    assert any("SQL" in r for r in it.requirements)


def test_ashby_compensation_summary():
    payload = {
        "jobs": [
            {
                "id": "j1",
                "title": "Product Design Intern",
                "employmentType": "Intern",
                "applyUrl": "https://jobs.ashbyhq.com/acme/j1",
                "publishedAt": "2025-02-01T00:00:00Z",
                "location": "Remote",
                "isRemote": True,
                "descriptionPlain": "Design things.",
                "compensation": {"compensationTierSummary": "$30/hr"},
            }
        ]
    }
    http = FakeHTTP({"api.ashbyhq.com": FakeResponse(payload)})
    src = AshbySource({"name": "Acme", "type": "ashby", "token": "acme"}, http)
    items = list(src.fetch())
    assert len(items) == 1
    assert items[0].salary == "$30/hr"
    assert items[0].remote is True


def test_workday_list_and_detail():
    list_payload = {
        "total": 1,
        "jobPostings": [
            {
                "title": "Summer 2025 Engineering Intern",
                "externalPath": "/job/NYC/Intern_R123",
                "locationsText": "New York",
                "startDate": "2025-01-20",
                "bulletFields": ["R123"],
            }
        ],
    }
    detail_payload = {
        "jobPostingInfo": {
            "jobDescription": "<p>Requirements</p><ul><li>Enrolled student</li></ul>"
                              "<p>Apply by March 1, 2025</p>",
            "location": "New York, NY",
            "startDate": "2025-01-20",
        }
    }

    def route(url):
        if "/wday/cxs/acme/External/job/" in url:
            return FakeResponse(detail_payload)
        return FakeResponse(list_payload)

    http = FakeHTTP({"myworkdayjobs.com": route})
    cfg = {
        "name": "Acme",
        "type": "workday",
        "host": "acme.wd5.myworkdayjobs.com",
        "tenant": "acme",
        "site": "External",
    }
    src = WorkdaySource(cfg, http)
    items = list(src.fetch())
    assert len(items) == 1
    it = items[0]
    assert it.title.startswith("Summer 2025")
    assert it.apply_url == "https://acme.wd5.myworkdayjobs.com/External/job/NYC/Intern_R123"
    assert any("Enrolled student" in r for r in it.requirements)
    assert it.deadline is not None and it.deadline.month == 3
