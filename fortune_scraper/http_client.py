"""A small, polite HTTP wrapper around requests with retries and a UA."""

from __future__ import annotations

import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (compatible; Fortune500InternshipBot/1.0; "
    "+https://github.com/jasonquachh/altf5)"
)


def build_session(
    timeout: float = 20.0,
    user_agent: str = DEFAULT_UA,
    max_retries: int = 3,
) -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=max_retries,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {"User-Agent": user_agent, "Accept": "application/json, text/html;q=0.9"}
    )

    # Bake a default timeout into every request without subclassing Session.
    original_request = session.request

    def _request(method, url, **kwargs):
        kwargs.setdefault("timeout", timeout)
        return original_request(method, url, **kwargs)

    session.request = _request  # type: ignore[assignment]
    return session


def polite_sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)
