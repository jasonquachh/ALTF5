from datetime import datetime, timezone

from fortune_scraper import parsing


class TestInternshipDetection:
    def test_positive_titles(self):
        assert parsing.looks_like_internship("Software Engineer Intern")
        assert parsing.looks_like_internship("2025 Summer Internship - Data Science")
        assert parsing.looks_like_internship("Finance Co-op")
        assert parsing.looks_like_internship("Co-Op, Mechanical Engineering")
        assert parsing.looks_like_internship("Summer 2026 Analyst Program")

    def test_negative_titles(self):
        assert not parsing.looks_like_internship("Senior Software Engineer")
        assert not parsing.looks_like_internship("Internal Communications Manager")
        assert not parsing.looks_like_internship("International Sales Lead")
        assert not parsing.looks_like_internship("Internist, Primary Care")
        assert not parsing.looks_like_internship("")

    def test_internship_in_body_wins_over_negative(self):
        # "international" present but it's clearly an internship.
        assert parsing.looks_like_internship(
            "Engineering Internship", "Open to international students"
        )


class TestHtmlToText:
    def test_strips_tags_and_keeps_bullets(self):
        html = "<p>Hello</p><ul><li>One</li><li>Two</li></ul><script>x=1</script>"
        text = parsing.html_to_text(html)
        assert "Hello" in text
        assert "• One" in text
        assert "• Two" in text
        assert "x=1" not in text

    def test_plain_passthrough(self):
        assert parsing.html_to_text("just text") == "just text"
        assert parsing.html_to_text(None) == ""


class TestSalary:
    def test_range_with_keyword(self):
        assert parsing.extract_salary("Compensation: $25 - $30 per hour") == "$25 - $30"

    def test_annual(self):
        out = parsing.extract_salary("The salary range is $90,000 to $110,000")
        assert "$90,000" in out and "$110,000" in out

    def test_none_when_absent(self):
        assert parsing.extract_salary("No numbers here") is None


class TestDeadline:
    def test_apply_by(self):
        dt = parsing.extract_deadline("Please apply by August 15, 2025.")
        assert dt == datetime(2025, 8, 15, tzinfo=timezone.utc)

    def test_iso_deadline(self):
        dt = parsing.extract_deadline("Application deadline: 2025-09-01")
        assert dt == datetime(2025, 9, 1, tzinfo=timezone.utc)

    def test_no_deadline(self):
        assert parsing.extract_deadline("Rolling applications") is None


class TestTimestamp:
    def test_iso_z(self):
        dt = parsing.parse_timestamp("2025-01-15T12:00:00Z")
        assert dt.year == 2025 and dt.tzinfo is not None

    def test_epoch_millis(self):
        dt = parsing.parse_timestamp(1700000000000)
        assert dt.year == 2023

    def test_epoch_seconds(self):
        dt = parsing.parse_timestamp(1700000000)
        assert dt.year == 2023

    def test_none(self):
        assert parsing.parse_timestamp(None) is None
        assert parsing.parse_timestamp("") is None


class TestRequirements:
    def test_extracts_under_header(self):
        text = (
            "About the role\nDo cool things\n"
            "Requirements\n"
            "• Pursuing a BS in CS\n"
            "• Python experience\n"
            "• Available summer 2025\n"
        )
        reqs = parsing.extract_requirements(text)
        assert any("BS in CS" in r for r in reqs)
        assert any("Python" in r for r in reqs)


class TestClosedDetection:
    def test_closed_markers(self):
        assert parsing.looks_closed("This position has been filled.")
        assert parsing.looks_closed("We are no longer accepting applications")
        assert not parsing.looks_closed("Apply now! We are hiring.")
