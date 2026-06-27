"""Heuristics for turning messy job-posting text into structured fields.

These functions are deliberately ATS-agnostic and side-effect free so they can
be unit tested without any network access.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Optional

# ---------------------------------------------------------------------------
# Internship detection
# ---------------------------------------------------------------------------

# Word-boundary matches so we don't trip on "internal" / "international".
_INTERN_PATTERNS = [
    r"\binterns?\b",
    r"\binternships?\b",
    r"\bco-?op\b",
    r"\bsummer\s+20\d{2}\b",
    r"\bindustrial\s+placement\b",
    r"\bplacement\s+year\b",
]
_INTERN_RE = re.compile("|".join(_INTERN_PATTERNS), re.IGNORECASE)

# Things that look intern-ish but are not student internships.
_INTERN_NEGATIVE_RE = re.compile(
    r"\b(internal\s+(only|posting|transfer)|intern(al)?\s+medicine|"
    r"internist|internationally?)\b",
    re.IGNORECASE,
)


def looks_like_internship(*texts: Optional[str]) -> bool:
    """True if any of the supplied strings indicates a student internship."""
    blob = " ".join(t for t in texts if t)
    if not blob.strip():
        return False
    if not _INTERN_RE.search(blob):
        return False
    # Guard against false positives, but only when there is no strong signal.
    if _INTERN_NEGATIVE_RE.search(blob) and not re.search(
        r"\binternship\b|\bco-?op\b|\bsummer\s+20\d{2}\b", blob, re.IGNORECASE
    ):
        return False
    return True


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


def html_to_text(html: Optional[str]) -> str:
    if not html:
        return ""
    if "<" not in html:  # already plain
        return html.strip()
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        # Fall back to a crude tag strip if the parser chokes.
        return re.sub(r"<[^>]+>", " ", html).strip()
    return parser.text()


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
