"""Fake web responses for tests. Nothing here touches the network."""
import io
import json
import urllib.error
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(*parts: str) -> dict:
    return json.loads((FIXTURES.joinpath(*parts)).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code: int, body: str = "", headers: dict | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://fake", code, "error", headers or {}, io.BytesIO(body.encode()))


class Router:
    """Stands in for http.opener. Routes are (method, url substring) -> response.

    A response is a dict (sent as JSON), an exception (raised), or a list of those (used in turn,
    the last one repeating). Every request is kept in .requests.
    """

    def __init__(self, routes: dict[tuple[str, str], object]):
        self.routes = routes
        self.requests = []

    def calls(self, method: str, fragment: str) -> int:
        return sum(1 for r in self.requests if r.get_method() == method and fragment in r.full_url)

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        for (method, fragment), response in self.routes.items():
            if req.get_method() == method and fragment in req.full_url:
                if isinstance(response, list):
                    response = response.pop(0) if len(response) > 1 else response[0]
                if isinstance(response, Exception):
                    raise response
                return FakeResponse(json.dumps(response).encode())
        raise AssertionError(f"Unexpected request: {req.get_method()} {req.full_url}")
