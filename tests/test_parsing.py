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


class TestEarlyCareerDetection:
    def test_new_grad_included(self):
        assert parsing.looks_like_internship("New Grad Software Engineer")
        assert parsing.looks_like_internship("University Graduate, Data Analyst")
        assert parsing.looks_like_internship("Early Career Rotational Program")

    def test_senior_roles_excluded(self):
        assert not parsing.looks_like_internship("Senior Software Engineer")
        assert not parsing.looks_like_internship("Staff Data Scientist")
        assert not parsing.looks_like_internship("Engineering Manager")
        # Title with no student/intern signal at all (the Stripe false positive).
        assert not parsing.looks_like_internship("Account Executive, Mid-Market")

    def test_detection_is_title_only(self):
        # Even if a description mentions interns, a non-intern title is rejected
        # because adapters now pass only the title.
        assert not parsing.looks_like_internship("Backend Engineer")


class TestProgramDetection:
    def test_named_programs_included(self):
        assert parsing.looks_like_internship("Microsoft Explore Program")
        assert parsing.looks_like_internship("Tech Discovery Program")
        assert parsing.looks_like_internship("Sophomore Insight Day")
        assert parsing.looks_like_internship("Engineering Externship")
        assert parsing.looks_like_internship("Women in Tech Fellowship")
        assert parsing.looks_like_internship("Emerging Talent Program")
        assert parsing.looks_like_internship("Scholars Program, Data Science")

    def test_premed_data_marketing_and_program_variety(self):
        # Pre-med / research / rotational program variety the user asked for.
        assert parsing.looks_like_internship("Summer Undergraduate Research Program")
        assert parsing.looks_like_internship("Pre-Med Summer Program")
        assert parsing.looks_like_internship("Leadership Development Program")
        assert parsing.looks_like_internship("Rotational Analyst Program")
        # Field-agnostic: any intern title qualifies regardless of discipline.
        assert parsing.looks_like_internship("Clinical Research Intern")
        assert parsing.looks_like_internship("Data Analytics Intern")
        assert parsing.looks_like_internship("Marketing Intern, Summer 2026")

    def test_non_student_programs_excluded(self):
        assert not parsing.looks_like_internship("Program Manager")
        assert not parsing.looks_like_internship("Director of Programs")
        assert not parsing.looks_like_internship("Senior Program Manager, Campus")
        assert not parsing.looks_like_internship("Engineering Program")  # no student signal
        assert not parsing.looks_like_internship("Research Scientist")   # no program word


class TestPaidDetection:
    def test_unpaid_flagged(self):
        assert parsing.looks_unpaid("This is an unpaid internship")
        assert parsing.looks_unpaid("Offered for academic credit only")
        assert parsing.looks_unpaid("This is a volunteer position")

    def test_paid_not_flagged(self):
        assert not parsing.looks_unpaid("Competitive salary and equity")
        assert not parsing.looks_unpaid("$30/hour plus benefits")
        assert not parsing.looks_unpaid(None)


class TestCategorize:
    def test_healthcare_first(self):
        assert parsing.categorize("Clinical Research Intern") == "healthcare"
        assert parsing.categorize("Biotech Lab Intern") == "healthcare"
        assert parsing.categorize("Pre-Med Summer Program") == "healthcare"
        assert parsing.categorize("Pharmacovigilance Intern") == "healthcare"

    def test_engineering(self):
        assert parsing.categorize("Software Engineering Intern") == "engineering"
        assert parsing.categorize("Mechanical Engineer Co-op") == "engineering"
        assert parsing.categorize("Data Engineer Intern") == "engineering"

    def test_business(self):
        assert parsing.categorize("Marketing Intern") == "business"
        assert parsing.categorize("Sales Development Intern") == "business"
        assert parsing.categorize("Finance Summer Analyst") == "business"

    def test_tech_catchall(self):
        assert parsing.categorize("Data Analytics Intern") == "tech"
        assert parsing.categorize("Product Design Intern") == "tech"
        assert parsing.categorize("Generalist Intern") == "tech"


class TestGraduateOnly:
    def test_grad_only_flagged(self):
        assert parsing.is_graduate_only("PhD Research Scientist Intern")
        assert parsing.is_graduate_only("Ph.D. Machine Learning Intern")
        assert parsing.is_graduate_only("MBA Summer Associate")
        assert parsing.is_graduate_only("Postdoctoral Fellow")

    def test_college_level_kept(self):
        assert not parsing.is_graduate_only("Software Engineering Intern")
        assert not parsing.is_graduate_only("New Grad Software Engineer")
        assert not parsing.is_graduate_only("Graduate Rotational Program")


class TestCleanSalary:
    def test_hourly_range(self):
        assert parsing.clean_salary("Compensation: $25 - $30 per hour") == "$25–$30/hr"

    def test_annual_range(self):
        out = parsing.clean_salary("salary range is $90,000 to $110,000 per year")
        assert out == "$90,000–$110,000/yr"

    def test_k_suffix_inferred_annual(self):
        assert parsing.clean_salary("$120k") == "$120,000/yr"

    def test_drops_implausible(self):
        # A stray "$3" or malformed value should not be shown.
        assert parsing.clean_salary("$3") is None
        assert parsing.clean_salary("Competitive pay") is None
        assert parsing.clean_salary(None) is None


class TestHtmlToText:
    def test_strips_tags_and_keeps_bullets(self):
        html = "<p>Hello</p><ul><li>One</li><li>Two</li></ul><script>x=1</script>"
        text = parsing.html_to_text(html)
        assert "Hello" in text
        assert "• One" in text
        assert "• Two" in text
        assert "x=1" not in text

    def test_decodes_entity_encoded_html(self):
        # Greenhouse returns HTML with entity-encoded angle brackets.
        raw = '&lt;div class=&quot;content-intro&quot;&gt;&lt;p&gt;Airbnb was born&lt;/p&gt;&lt;/div&gt;'
        text = parsing.html_to_text(raw)
        assert "Airbnb was born" in text
        assert "&lt;" not in text and "<div" not in text and "&quot;" not in text

    def test_plain_passthrough(self):
        assert parsing.html_to_text("just text") == "just text"
        assert parsing.html_to_text(None) == ""


class TestUSLocation:
    def test_us_locations(self):
        assert parsing.location_us_status("New York, NY") is True
        assert parsing.location_us_status("San Francisco, CA") is True
        assert parsing.location_us_status("Seattle, Washington") is True
        assert parsing.location_us_status("Remote, US") is True
        assert parsing.location_us_status("Remote") is True

    def test_non_us_locations(self):
        assert parsing.location_us_status("São Paulo, Brazil") is False
        assert parsing.location_us_status("Milan, Italy") is False
        assert parsing.location_us_status("London, UK") is False
        assert parsing.location_us_status("Toronto, Canada") is False
        assert parsing.location_us_status("Bengaluru, India") is False
        assert parsing.location_us_status("Remote - EMEA") is False

    def test_filter_keeps_only_us(self):
        is_us, locs = parsing.filter_us_locations(["New York, NY", "London, UK"])
        assert is_us is True
        assert locs == ["New York, NY"]

        is_us, locs = parsing.filter_us_locations(["Milan, Italy"])
        assert is_us is False
        assert locs == []


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
