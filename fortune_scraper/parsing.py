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
# Internship / early-career detection
#
# The audience is people still in school or who just finished university, and
# undergraduates must be eligible. So we accept two kinds of role:
#   * unambiguous internships / co-ops / summer programs, and
#   * new-grad / early-career / campus roles that are NOT senior/experienced.
# Detection runs on the *title* (and ATS commitment/employment-type fields),
# never the long description body, to avoid false positives from boilerplate
# that merely mentions interns.
# ---------------------------------------------------------------------------

# Unambiguous student-internship signals.
_INTERN_STRONG_RE = re.compile(
    r"\b(interns?|internships?|co-?op|summer\s+analyst|summer\s+associate|"
    r"industrial\s+placement|placement\s+year|apprentice(?:ship)?|trainee)\b",
    re.IGNORECASE,
)
_SUMMER_YEAR_RE = re.compile(r"\bsummer\s+20\d{2}\b", re.IGNORECASE)

# Broader student / recent-grad roles (only when not senior — see below).
_EARLY_CAREER_RE = re.compile(
    r"\b(new\s+grad(?:uate)?|recent\s+graduate|university\s+graduate|"
    r"graduate\s+(?:programme|program|scheme|analyst)|early\s+career|"
    r"early\s+talent|campus\s+(?:hire|program|ambassador)|working\s+student|"
    r"student\s+(?:worker|position|role))\b",
    re.IGNORECASE,
)

# Experienced / leadership signals that disqualify a role for students.
_SENIOR_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|head\s+of|"
    r"vp|vice\s+president|experienced|expert|architect|fellow|"
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
    """True if the supplied title/commitment text describes a student-eligible
    internship or early-career role (and not a senior/experienced position)."""
    blob = " ".join(t for t in texts if t).strip()
    if not blob:
        return False

    # 1) Unambiguous internship signals win outright.
    if _INTERN_STRONG_RE.search(blob) or _SUMMER_YEAR_RE.search(blob):
        if _INTERN_NEGATIVE_RE.search(blob) and not re.search(
            r"\b(internship|co-?op|summer\s+20\d{2})\b", blob, re.IGNORECASE
        ):
            return False
        return True

    # 2) New-grad / early-career roles, but never senior/experienced ones.
    if _EARLY_CAREER_RE.search(blob) and not _SENIOR_RE.search(blob):
        return True

    return False


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
