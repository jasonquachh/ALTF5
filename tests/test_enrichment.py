from fortune_scraper import parsing
from fortune_scraper.enrichment import enrich, needs_enrichment
from fortune_scraper.models import Internship
from tests.conftest import FakeHTTP, FakeResponse


class TestSummarize:
    def test_sentence_bounded(self):
        text = "Affirm is reinventing credit. " * 40
        out = parsing.summarize(text, 100)
        assert len(out) <= 101
        assert not out.endswith("reinv")  # never mid-word
        assert out.endswith(".") or out.endswith("…")

    def test_short_passthrough(self):
        assert parsing.summarize("Short role.", 400) == "Short role."
        assert parsing.summarize(None) == ""


class TestRequirementHeaders:
    def test_excludes_responsibilities(self):
        text = (
            "What you'll do\n"
            "• You will work on tasks that contribute to the team\n"
            "• You will contribute to a sense of community\n"
            "Qualifications\n"
            "• Pursuing a BS in Computer Science\n"
            "• Familiarity with Python\n"
        )
        reqs = parsing.extract_requirements(text)
        assert any("Computer Science" in r for r in reqs)
        assert not any("sense of community" in r for r in reqs)


class TestEnrichment:
    def test_enriches_from_greenhouse(self):
        # A bare aggregator posting pointing at a Greenhouse job URL.
        item = Internship(
            source="intern-list", external_id="x", company="Layup Parts",
            title="Software Engineering Intern",
            apply_url="https://job-boards.greenhouse.io/layupparts/jobs/4567",
            locations=["Huntington Beach, CA"],
        )
        assert needs_enrichment(item)
        job = {
            "content": "<p>Build rockets. Compensation: $30 - $40 per hour.</p>"
                       "<h3>Requirements</h3><ul><li>Pursuing a BS in Mechanical "
                       "Engineering</li><li>CAD experience</li></ul>",
            "location": {"name": "Huntington Beach, CA"},
        }
        http = FakeHTTP({"boards-api.greenhouse.io/v1/boards/layupparts/jobs/4567":
                         FakeResponse(job)})
        enrich(item, http)
        assert item.description and "Build rockets" in item.description
        assert any("Mechanical" in r for r in item.requirements)
        assert item.salary == "$30 - $40"

    def test_complete_item_skipped(self):
        item = Internship(
            source="greenhouse", external_id="1", company="Acme", title="Intern",
            apply_url="https://x/1", description="Full desc",
            requirements=["a"], salary="$30/hr",
        )
        assert not needs_enrichment(item)
        http = FakeHTTP({})           # no routes -> would error if called
        enrich(item, http)            # must be a no-op
        assert item.description == "Full desc"
