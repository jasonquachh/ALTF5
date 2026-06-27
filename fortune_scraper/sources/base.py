"""Base class shared by every ATS adapter."""

from __future__ import annotations

import logging
from typing import Iterator

from ..models import Internship

log = logging.getLogger(__name__)


class Source:
    """Abstract source. Subclasses implement :meth:`fetch`.

    `company_cfg` is one entry from companies.yaml, e.g.::

        {"name": "Acme", "type": "greenhouse", "token": "acme"}
    """

    type: str = "base"

    def __init__(self, company_cfg: dict, http) -> None:
        self.cfg = company_cfg
        self.http = http
        self.company = company_cfg.get("name", company_cfg.get("token", "Unknown"))

    # -- public API ---------------------------------------------------------

    def fetch(self) -> Iterator[Internship]:
        """Yield every *internship* posting currently live for this company."""
        raise NotImplementedError

    # -- helpers ------------------------------------------------------------

    def _get_json(self, url: str, **kwargs):
        resp = self.http.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _post_json(self, url: str, json=None, **kwargs):
        resp = self.http.post(url, json=json, **kwargs)
        resp.raise_for_status()
        return resp.json()
