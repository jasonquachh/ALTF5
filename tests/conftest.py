"""Shared test helpers: a fake HTTP session that replays canned responses."""

import json as jsonlib


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text="", headers=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text else (jsonlib.dumps(payload) if payload is not None else "")
        self.headers = headers or {"Content-Type": "application/json"}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHTTP:
    """Maps URL substrings -> FakeResponse (or a callable taking the url)."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []

    def _match(self, url):
        for key, resp in self.routes.items():
            if key in url:
                return resp(url) if callable(resp) else resp
        return FakeResponse(status_code=404, text="not found")

    def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        return self._match(url)

    def post(self, url, json=None, **kwargs):
        self.calls.append(("POST", url, json))
        return self._match(url)
