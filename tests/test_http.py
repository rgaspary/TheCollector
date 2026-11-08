import base64
import io
import json
import unittest
import urllib.error
from unittest import mock

from collector import http


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code: int, body: str = "", headers: dict | None = None):
    return urllib.error.HTTPError("https://x", code, "err", headers or {}, io.BytesIO(body.encode()))


class FakeOpener:
    """Returns or raises the queued results in order and records each request."""

    def __init__(self, *results):
        self.results = list(results)
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return FakeResponse(json.dumps(result).encode())


class RequestJson(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(http, "sleep", lambda s: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def use(self, opener):
        patcher = mock.patch.object(http, "opener", opener)
        patcher.start()
        self.addCleanup(patcher.stop)
        return opener

    def test_retries_429_then_succeeds(self):
        opener = self.use(FakeOpener(http_error(429, headers={"Retry-After": "0"}), {"ok": 1}))
        self.assertEqual(http.request_json("GET", "https://x"), {"ok": 1})
        self.assertEqual(len(opener.requests), 2)

    def test_gives_up_after_retries(self):
        self.use(FakeOpener(*[http_error(429, headers={"Retry-After": "0"})] * 3))
        with self.assertRaises(http.HttpError) as cm:
            http.request_json("GET", "https://x")
        self.assertEqual(cm.exception.status, 429)
        self.assertEqual(cm.exception.retry_after, 0)

    def test_raises_http_error_with_status(self):
        self.use(FakeOpener(http_error(403, "nope")))
        with self.assertRaises(http.HttpError) as cm:
            http.request_json("GET", "https://x")
        self.assertEqual(cm.exception.status, 403)
        self.assertEqual(cm.exception.body, "nope")

    def test_network_error_is_status_0(self):
        self.use(FakeOpener(urllib.error.URLError("no route")))
        with self.assertRaises(http.HttpError) as cm:
            http.request_json("GET", "https://x")
        self.assertEqual(cm.exception.status, 0)

    def test_basic_auth_header(self):
        opener = self.use(FakeOpener({}))
        http.request_json("POST", "https://x", basic_auth=("id", "secret"), form={"a": "b"})
        req = opener.requests[0]
        self.assertEqual(req.get_header("Authorization"), "Basic " + base64.b64encode(b"id:secret").decode())
        self.assertEqual(req.data, b"a=b")
        self.assertEqual(req.get_method(), "POST")

    def test_json_body_and_params(self):
        opener = self.use(FakeOpener({}))
        http.request_json("POST", "https://x/p", params={"q": "a b"}, json_body={"k": 1})
        req = opener.requests[0]
        self.assertEqual(req.full_url, "https://x/p?q=a+b")
        self.assertEqual(json.loads(req.data), {"k": 1})
        self.assertEqual(req.get_header("Content-type"), "application/json")

    def test_empty_body_is_empty_dict(self):
        opener = self.use(FakeOpener({}))
        opener.results = []
        with mock.patch.object(http, "opener", lambda req, timeout=None: FakeResponse(b"")):
            self.assertEqual(http.request_json("GET", "https://x"), {})


if __name__ == "__main__":
    unittest.main()
