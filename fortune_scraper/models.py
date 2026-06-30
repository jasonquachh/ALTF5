"""Core data models for scraped internship postings."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Internship:
    """A single internship posting normalized across every ATS source.

    All sources (Greenhouse, Lever, Ashby, Workday, ...) are mapped into this
    shape so that the rest of the pipeline — dedup, verification, Discord
    formatting — never has to care where a posting came from.
    """

    # Identity
    source: str                      # e.g. "greenhouse", "lever"
    external_id: str                 # the ATS's own id for the posting
    company: str                     # human readable company name
    title: str
    apply_url: str

    # Key announcement details (the user explicitly asked for these)
    release_date: Optional[datetime] = None   # when the posting went live
    deadline: Optional[datetime] = None        # application deadline, if any
    locations: list[str] = field(default_factory=list)
    salary: Optional[str] = None               # human-readable comp string
    requirements: list[str] = field(default_factory=list)

    # Extra context
    department: Optional[str] = None
    employment_type: Optional[str] = None      # e.g. "Internship", "Co-op"
    remote: Optional[bool] = None
    description: Optional[str] = None           # plain-text, truncated upstream
    category: Optional[str] = None             # healthcare/engineering/tech/business

    # Bookkeeping
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def uid(self) -> str:
        """Stable, globally-unique key used for deduplication."""
        basis = f"{self.source}:{self.external_id}"
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()

    @property
    def primary_location(self) -> str:
        if self.remote and not self.locations:
            return "Remote"
        if not self.locations:
            return "Not specified"
        head = self.locations[0]
        extra = len(self.locations) - 1
        return f"{head} (+{extra} more)" if extra > 0 else head

    def to_record(self) -> dict[str, Any]:
        """Flatten to a JSON-serializable dict for the dedup store."""
        d = asdict(self)
        d.pop("raw", None)
        for key in ("release_date", "deadline"):
            val = getattr(self, key)
            d[key] = val.isoformat() if val else None
        d["uid"] = self.uid
        return d

    def __str__(self) -> str:
        return f"[{self.company}] {self.title} <{self.source}:{self.external_id}>"
