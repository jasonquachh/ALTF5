"""Heuristics for turning messy job-posting text into structured fields.

These functions are deliberately ATS-agnostic and side-effect free so they can
be unit tested without any network access.
"""

from __future__ import annotations

import html as _htmllib
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Optional

# ---------------------------------------------------------------------------
# Student-opportunity detection
#
# We want any opportunity aimed at helping a student's career: internships,
# co-ops, and the many named "programs" companies run — explore / discovery /
# insight / scholars / externships / sophomore & freshman programs, etc. The
# audience is people still in school or who just finished university, and
# undergraduates must be eligible, so we exclude senior/experienced roles.
# Detection runs on the *title* (and ATS commitment/employment-type fields),
# never the long description body, to avoid false positives from boilerplate.
# ---------------------------------------------------------------------------

# Unambiguous student-internship signals.
_INTERN_STRONG_RE = re.compile(
    r"\b(interns?|internships?|co-?op|summer\s+analyst|summer\s+associate|"
    r"industrial\s+placement|placement\s+year|apprentice(?:ship)?|trainee|"
    r"externship)\b",
    re.IGNORECASE,
)
_SUMMER_YEAR_RE = re.compile(r"\bsummer\s+20\d{2}\b", re.IGNORECASE)

# Broader student / recent-grad roles (only when not senior — see below).
_EARLY_CAREER_RE = re.compile(
    r"\b(new\s+grad(?:uate)?|recent\s+graduate|university\s+graduate|"
    r"graduate\s+(?:programme|program|scheme|analyst)|early\s+career|"
    r"early\s+talent|emerging\s+talent|campus\s+(?:hire|program|ambassador)|"
    r"working\s+student|student\s+(?:worker|position|role|opportunit\w+))\b",
    re.IGNORECASE,
)

# Named student/career programs: a student signal next to a "program" word, plus
# a few standalone program types. Catches Microsoft Explore, "...Discovery
# Program", "Insight Day", "Sophomore Scholars", externships, fellowships, etc.
_PROGRAM_SIGNAL = (
    r"(?:explore\w*|discover\w*|insight\w*|emerging\s+talent|future\s+leaders?|"
    r"rising\s+(?:sophomore|junior|senior)|sophomore|freshman|first[-\s]?year|"
    r"scholars?|pathways?|launch|ignite|catalyst|propel|elevate|spark|immersion|"
    r"academy|student|students|campus|university|college|undergrad\w*|"
    r"early[-\s]?(?:career|talent|insight)|women(?:'s|s)?|diversity|"
    r"underrepresented|rotational|leadership\s+development|research|"
    r"pre[-\s]?med\w*|pre[-\s]?health\w*|summer)"
)
_PROGRAM_WORD = (
    r"(?:program|programme|scheme|experience|cohort|fellowship|externship|"
    r"academy|institute|bootcamp|residency|pipeline|initiative|"
    r"insight\s+days?|days?|series)"
)
_PROGRAM_RE = re.compile(
    r"\b(?:externship|fellowship)\b"
    r"|\b" + _PROGRAM_SIGNAL + r"[\w&/,'\- ]{0,30}?\b" + _PROGRAM_WORD + r"\b"
    r"|\b" + _PROGRAM_WORD + r"[\w&/,'\- ]{0,30}?\b" + _PROGRAM_SIGNAL + r"\b",
    re.IGNORECASE,
)

# Experienced / leadership signals that disqualify a role for students.
_SENIOR_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|head\s+of|"
    r"vp|vice\s+president|experienced|expert|architect|"
    r"ii|iii|iv|2|3)\b",
    re.IGNORECASE,
)

# Things that look intern-ish but are not student internships.
_INTERN_NEGATIVE_RE = re.compile(
    r"\b(internal\s+(only|posting|transfer|communications?|audit|mobility)|"
    r"intern(al)?\s+medicine|internist|internationally?)\b",
    re.IGNORECASE,
)


def looks_like_internship(*texts: Optional[str]) -> bool:
    """True if the title/commitment describes a student-eligible internship,
    co-op, or career program (and not a senior/experienced position)."""
    blob = " ".join(t for t in texts if t).strip()
    if not blob:
        return False

    # 1) Unambiguous internship signals win outright.
    if _INTERN_STRONG_RE.search(blob) or _SUMMER_YEAR_RE.search(blob):
        if _INTERN_NEGATIVE_RE.search(blob) and not re.search(
            r"\b(internship|co-?op|summer\s+20\d{2}|externship)\b", blob, re.IGNORECASE
        ):
            return False
        return True

    # 2) New-grad / early-career roles and named student programs, but never
    #    senior/experienced ones.
    if (_EARLY_CAREER_RE.search(blob) or _PROGRAM_RE.search(blob)) and not \
            _SENIOR_RE.search(blob):
        return True

    return False


# ---------------------------------------------------------------------------
# College-level vs graduate/PhD focus
# ---------------------------------------------------------------------------

# Roles aimed at PhD / master's / MBA / postdoc audiences. We de-emphasize these
# in favor of college (undergraduate) opportunities. Note: "new grad" and
# "graduate program / rotational" target bachelor's grads and are NOT excluded.
_GRADUATE_ONLY_RE = re.compile(
    r"\b(ph\.?\s?d\.?|phd|doctoral|doctorate|post[-\s]?doc\w*|"
    r"master'?s\s+(?:degree|student|candidate)|mba|"
    r"graduate\s+student|grad\s+student|ms/phd|m\.?s\.?/ph)\b",
    re.IGNORECASE,
)


def is_graduate_only(title: Optional[str]) -> bool:
    """True for PhD/master's/MBA/postdoc-targeted roles (not college-level)."""
    if not title:
        return False
    return bool(_GRADUATE_ONLY_RE.search(title))


# ---------------------------------------------------------------------------
# Category classification (which Discord channel a role belongs to)
# ---------------------------------------------------------------------------

CATEGORIES = ("healthcare", "engineering", "tech", "business")

_CAT_HEALTHCARE_RE = re.compile(
    r"\b(health\w*|medical|medicine|clinic\w*|biotech\w*|biolog\w*|pharma\w*|"
    r"nurs\w*|patient|life\s+sciences?|genomics?|genetics?|bioinformatics?|"
    r"pre[-\s]?med\w*|pre[-\s]?health\w*|epidemiolog\w*|public\s+health|"
    r"therapeutics?|oncolog\w*|immunolog\w*|neuroscience|wet\s+lab|laboratory|"
    r"clinical|drug\s+discovery|biomedical|physician|hospital)\b",
    re.IGNORECASE,
)
_CAT_ENGINEERING_RE = re.compile(
    r"\b(software\s+engineer\w*|swe|engineering|engineer|developer|backend|"
    r"back-end|frontend|front-end|full[-\s]?stack|devops|sre|"
    r"site\s+reliability|infrastructure|platform\s+engineer|embedded|firmware|"
    r"hardware|mechanical|electrical|civil|aerospace|robotics|systems\s+engineer|"
    r"ml\s+engineer|machine\s+learning\s+engineer|data\s+engineer|"
    r"security\s+engineer|qa\s+engineer|test\s+engineer)\b",
    re.IGNORECASE,
)
_CAT_TECH_RE = re.compile(
    r"\b(product\s+manager|product\s+management|product\s+design|ux|ui|"
    r"designer|\bdesign\b|data\s+scien\w*|data\s+analy\w*|analytics|"
    r"machine\s+learning|artificial\s+intelligence|\bai\b|\bml\b|"
    r"research\s+scien\w*|information\s+technology|\bit\b|technical\s+program|"
    r"\bqa\b|quality\s+assurance|cyber\s?security|\bsecurity\b|product\b)\b",
    re.IGNORECASE,
)
_CAT_BUSINESS_RE = re.compile(
    r"\b(marketing|sales|business\s+development|bizdev|account\s+executive|"
    r"finance|financial|accounting|operations|\bops\b|human\s+resources|\bhr\b|"
    r"recruit\w*|people\s+team|talent|strategy|consult\w*|partnerships?|"
    r"communications?|\bpr\b|legal|growth|revenue|customer\s+success|"
    r"supply\s+chain|procurement|brand|content|social\s+media|community|"
    r"administrative|program\s+management|project\s+manager)\b",
    re.IGNORECASE,
)


def categorize(title: Optional[str], department: Optional[str] = None,
               description: Optional[str] = None) -> str:
    """Sort a posting into one of CATEGORIES. Healthcare is checked first (the
    user wants extensive pre-med/healthcare coverage); tech is the catch-all."""
    blob = " ".join(t for t in (title, department) if t)
    if not blob.strip():
        blob = (description or "")[:200]
    if _CAT_HEALTHCARE_RE.search(blob):
        return "healthcare"
    if _CAT_ENGINEERING_RE.search(blob):
        return "engineering"
    if _CAT_BUSINESS_RE.search(blob):
        return "business"
    if _CAT_TECH_RE.search(blob):
        return "tech"
    return "tech"


# ---------------------------------------------------------------------------
# Salary sanitization (only show reasonable, sensible compensation)
# ---------------------------------------------------------------------------

_PERIOD_RE = re.compile(
    r"(per\s+hour|/\s?hour|/\s?hr|\bhourly\b|\bhr\b|"
    r"per\s+week|/\s?week|/\s?wk|\bweekly\b|"
    r"per\s+month|/\s?month|/\s?mo\b|\bmonthly\b|\bmonth\b|"
    r"per\s+(?:year|annum)|/\s?year|/\s?yr|\bannual\w*|\byear\b|\byr\b)",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(r"[$£€]?\s?(\d{1,3}(?:[,\.]\d{3})+|\d+(?:\.\d+)?)\s?([kK])?")

# Plausible internship comp ranges, per period.
_PLAUSIBLE = {
    "hour": (7.0, 250.0),
    "week": (200.0, 8000.0),
    "month": (800.0, 40000.0),
    "year": (15000.0, 500000.0),
}
_SUFFIX = {"hour": "hr", "week": "wk", "month": "mo", "year": "yr"}


def _to_amount(num: str, k: Optional[str]) -> Optional[float]:
    s = num.strip()
    try:
        if k:                         # "45k"
            return float(s.replace(",", "")) * 1000
        if "," in s:                  # US thousands: 90,000
            return float(s.replace(",", ""))
        if "." in s:
            intpart, _, frac = s.partition(".")
            if len(frac) == 3 and frac.isdigit():   # European thousands: 3.000
                return float(intpart + frac)
            return float(s)
        return float(s)
    except ValueError:
        return None


def _detect_period(text: str) -> Optional[str]:
    m = _PERIOD_RE.search(text)
    if not m:
        return None
    tok = m.group(0).lower()
    if "hour" in tok or "/hr" in tok or tok.strip() == "hr" or "hourly" in tok:
        return "hour"
    if "week" in tok or "/wk" in tok or "weekly" in tok:
        return "week"
    if "month" in tok or "/mo" in tok or "monthly" in tok:
        return "month"
    return "year"


def _infer_period(hi: float) -> Optional[str]:
    if hi <= 250:
        return "hour"
    if hi <= 9000:
        return "month"
    if hi <= 500000:
        return "year"
    return None


def _fmt_amount(x: float, period: str) -> str:
    if period == "hour":
        return f"${x:,.2f}".rstrip("0").rstrip(".")
    return f"${x:,.0f}"


def clean_salary(raw: Optional[str]) -> Optional[str]:
    """Return a tidy, plausible comp string, or None if it can't be validated.

    Drops nonsense (e.g. a stray "$3.000" or a single huge number) so the
    Discord embed never shows a salary that doesn't make sense.
    """
    if not raw:
        return None
    text = str(raw)
    amounts = []
    for m in _MONEY_RE.finditer(text):
        amt = _to_amount(m.group(1), m.group(2))
        if amt and amt > 0:
            amounts.append(amt)
    if not amounts:
        return None
    lo, hi = min(amounts), max(amounts)
    period = _detect_period(text) or _infer_period(hi)
    if period is None:
        return None
    plo, phi = _PLAUSIBLE[period]
    if not (plo <= lo <= phi and plo <= hi <= phi):
        return None
    suffix = _SUFFIX[period]
    if abs(hi - lo) < 1e-6:
        return f"{_fmt_amount(lo, period)}/{suffix}"
    return f"{_fmt_amount(lo, period)}–{_fmt_amount(hi, period)}/{suffix}"


# ---------------------------------------------------------------------------
# Paid / unpaid detection
# ---------------------------------------------------------------------------

_UNPAID_RE = re.compile(
    r"\b(unpaid|without\s+(?:pay|compensation)|no\s+(?:pay|compensation|salary|"
    r"stipend|monetary)|not\s+(?:a\s+)?paid|volunteer|voluntary|"
    r"(?:course|academic|school)\s+credit\s+only|"
    r"only\s+(?:for\s+)?(?:course|academic|school)\s+credit)\b",
    re.IGNORECASE,
)


def looks_unpaid(text: Optional[str]) -> bool:
    """True only when a posting explicitly states it is unpaid / for credit."""
    if not text:
        return False
    return bool(_UNPAID_RE.search(text))


# ---------------------------------------------------------------------------
# HTML -> plain text
# ---------------------------------------------------------------------------


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in ("br", "p", "li", "div", "tr", "h1", "h2", "h3", "h4"):
            self._parts.append("\n")
        if tag == "li":
            self._parts.append("• ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        joined = "".join(self._parts)
        joined = re.sub(r"[ \t]+", " ", joined)
        joined = re.sub(r"\n\s*\n\s*\n+", "\n\n", joined)
        return joined.strip()


def html_to_text(raw: Optional[str]) -> str:
    if not raw:
        return ""
    # Some ATS APIs (e.g. Greenhouse) return HTML with its angle brackets
    # entity-encoded (`&lt;div&gt;...`). Decode entities first so the markup
    # actually parses instead of leaking "&lt;div class=..." into the output.
    text = _htmllib.unescape(raw)
    if "<" not in text:  # already plain
        return _collapse_ws(text)
    parser = _TextExtractor()
    try:
        parser.feed(text)
    except Exception:
        # Fall back to a crude tag strip if the parser chokes.
        return _collapse_ws(re.sub(r"<[^>]+>", " ", text))
    return parser.text()


def _collapse_ws(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Salary / compensation
# ---------------------------------------------------------------------------

_CURRENCY = r"[$£€]"
_MONEY = rf"{_CURRENCY}\s?\d[\d,]*(?:\.\d+)?\s?[kK]?"
_SALARY_RE = re.compile(
    rf"({_MONEY}(?:\s?(?:-|to|–|—)\s?{_MONEY})?"
    rf"(?:\s?(?:per|/|an?)\s?(?:hour|hr|month|mo|year|yr|annum|week|wk))?)",
    re.IGNORECASE,
)
_SALARY_CONTEXT_RE = re.compile(
    r"(salary|compensation|pay\s*range|hourly\s*rate|base\s*pay|stipend)"
    rf"[^.\n]{{0,60}}?({_MONEY}(?:\s?(?:-|to|–|—)\s?{_MONEY})?)",
    re.IGNORECASE,
)


def extract_salary(text: Optional[str]) -> Optional[str]:
    """Best-effort comp string. Prefers ranges near salary keywords."""
    if not text:
        return None
    ctx = _SALARY_CONTEXT_RE.search(text)
    if ctx:
        return _clean_money(ctx.group(2))
    m = _SALARY_RE.search(text)
    if m:
        return _clean_money(m.group(1))
    return None


def _clean_money(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# Deadline
# ---------------------------------------------------------------------------

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
_DEADLINE_KEYWORDS = (
    r"(?:apply\s+by|applications?\s+(?:close|due|deadline)|"
    r"deadline|closing\s+date|close[sd]?\s+on|last\s+day\s+to\s+apply)"
)
_DEADLINE_TEXT_RE = re.compile(
    rf"{_DEADLINE_KEYWORDS}[^.\n]{{0,40}}?"
    rf"((?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s*\d{{4}}?"
    rf"|\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}"
    rf"|\d{{4}}-\d{{2}}-\d{{2}})",
    re.IGNORECASE,
)

_DATE_FORMATS = (
    "%B %d %Y", "%B %d, %Y", "%b %d %Y", "%b %d, %Y",
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%d/%m/%Y",
)


def extract_deadline(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    m = _DEADLINE_TEXT_RE.search(text)
    if not m:
        return None
    return _parse_date(m.group(1))


def _parse_date(raw: str) -> Optional[datetime]:
    cleaned = re.sub(r"(\d)(st|nd|rd|th)", r"\1", raw).replace(",", "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def parse_timestamp(value) -> Optional[datetime]:
    """Parse the many timestamp shapes ATS APIs emit into aware UTC datetimes."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        # Milliseconds vs seconds since epoch.
        ts = value / 1000.0 if value > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return parse_timestamp(int(s))
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        return _parse_date(s)
    return None


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------

_REQ_HEADER_RE = re.compile(
    r"(requirements?|qualifications?|what\s+(?:you'?ll|we'?re\s+looking)|"
    r"who\s+you\s+are|minimum\s+qualifications?|basic\s+qualifications?|"
    r"what\s+you\s+(?:need|bring))",
    re.IGNORECASE,
)


def extract_requirements(text: Optional[str], limit: int = 6) -> list[str]:
    """Pull bullet-style requirements out of a plain-text description."""
    if not text:
        return []
    lines = [ln.strip() for ln in text.splitlines()]
    out: list[str] = []
    capturing = False
    for ln in lines:
        if not ln:
            continue
        if _REQ_HEADER_RE.search(ln) and len(ln) < 80:
            capturing = True
            continue
        if capturing:
            bullet = ln.lstrip("•-*–— ").strip()
            # Stop when we hit a new non-bullet section header.
            if not bullet:
                continue
            if len(bullet) > 3:
                out.append(truncate(bullet, 180))
            if len(out) >= limit:
                break
    # Fallback: just grab the first few bullet lines anywhere.
    if not out:
        for ln in lines:
            b = ln.lstrip()
            if b[:1] in "•-*–" and len(b) > 4:
                out.append(truncate(b.lstrip("•-*–— "), 180))
            if len(out) >= limit:
                break
    return out


# ---------------------------------------------------------------------------
# Closed / unavailable detection (used by the verifier)
# ---------------------------------------------------------------------------

_CLOSED_MARKERS = (
    "no longer accepting applications",
    "no longer available",
    "this position has been filled",
    "position is closed",
    "applications are closed",
    "job posting is closed",
    "this role is closed",
    "no longer open",
    "posting has expired",
    "this job is no longer",
    "not currently accepting applications",
)


def looks_closed(page_text: Optional[str]) -> bool:
    if not page_text:
        return False
    low = page_text.lower()
    return any(marker in low for marker in _CLOSED_MARKERS)


# ---------------------------------------------------------------------------
# US-only location filtering
# ---------------------------------------------------------------------------

_US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}
_US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia",
}
_US_POSITIVE = (
    "united states", "u.s.a", "u.s.a.", "usa", "u.s.", "u. s.",
    "remote - us", "remote, us", "remote (us", "us remote", "remote us",
    "us-remote", "(us)", ", us", "- us", "united states of america",
)
# Countries and macro-regions that are clearly NOT the US.
_NON_US = (
    "canada", "mexico", "brazil", "brasil", "argentina", "chile", "colombia",
    "peru", "uruguay", "costa rica", "united kingdom", "u.k.", "uk", "england",
    "scotland", "wales", "northern ireland", "ireland", "france", "germany",
    "spain", "portugal", "italy", "netherlands", "belgium", "luxembourg",
    "switzerland", "austria", "sweden", "norway", "denmark", "finland",
    "iceland", "poland", "czech", "czechia", "slovakia", "hungary", "romania",
    "bulgaria", "greece", "croatia", "serbia", "ukraine", "estonia", "latvia",
    "lithuania", "turkey", "israel", "united arab emirates", "u.a.e", "uae",
    "dubai", "abu dhabi", "saudi", "qatar", "kuwait", "bahrain", "egypt",
    "morocco", "south africa", "nigeria", "kenya", "ghana", "india", "pakistan",
    "bangladesh", "sri lanka", "china", "hong kong", "taiwan", "japan",
    "south korea", "korea", "singapore", "malaysia", "indonesia", "thailand",
    "vietnam", "philippines", "australia", "new zealand",
    # Macro-regions used in remote postings.
    "emea", "apac", "latam", "asia pacific", "asia-pacific", "europe",
    "middle east", "africa", "oceania",
)


def location_us_status(loc: Optional[str]):
    """Return True (US), False (definitely non-US), or None (unknown)."""
    if not loc:
        return None
    low = loc.lower()
    for token in _NON_US:
        if re.search(r"\b" + re.escape(token) + r"\b", low):
            return False
    if any(p in low for p in _US_POSITIVE):
        return True
    m = re.search(r",\s*([A-Za-z]{2})\b", loc)
    if m and m.group(1).upper() in _US_STATE_CODES:
        return True
    for name in _US_STATE_NAMES:
        if re.search(r"\b" + name + r"\b", low):
            return True
    if "remote" in low:   # bare "Remote" with no foreign marker → treat as US
        return True
    return None


def filter_us_locations(locations: list[str]):
    """Given a posting's locations, return (is_us, us_locations).

    `is_us` is True only when at least one location is positively in the US.
    The returned list contains just the US-based locations, so announcements
    never show foreign offices.
    """
    us = [loc for loc in locations if location_us_status(loc) is True]
    return (bool(us), us)
