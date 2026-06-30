"""ATS source adapters.

Each adapter knows how to talk to one applicant-tracking system and yield
normalized :class:`~fortune_scraper.models.Internship` objects.
"""

from __future__ import annotations

from typing import Type

from .base import Source
from .greenhouse import GreenhouseSource
from .lever import LeverSource
from .ashby import AshbySource
from .workday import WorkdaySource
from .json_list import JsonListSource

# Registry keyed by the `type` field used in companies.yaml.
REGISTRY: dict[str, Type[Source]] = {
    GreenhouseSource.type: GreenhouseSource,
    LeverSource.type: LeverSource,
    AshbySource.type: AshbySource,
    WorkdaySource.type: WorkdaySource,
    JsonListSource.type: JsonListSource,
}


def build_source(company_cfg: dict, http) -> Source:
    """Instantiate the right adapter for a company config block."""
    stype = company_cfg.get("type")
    if stype not in REGISTRY:
        raise ValueError(
            f"Unknown source type {stype!r} for {company_cfg.get('name')!r}. "
            f"Known types: {sorted(REGISTRY)}"
        )
    return REGISTRY[stype](company_cfg, http)


__all__ = [
    "Source",
    "GreenhouseSource",
    "LeverSource",
    "AshbySource",
    "WorkdaySource",
    "JsonListSource",
    "REGISTRY",
    "build_source",
]
