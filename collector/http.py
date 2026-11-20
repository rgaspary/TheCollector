"""The one place TheCollector talks to web APIs. Tests replace `opener` (and `sleep`)."""
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPException
from pathlib import Path

from . import __version__

TIMEOUT = 20
MAX_RETRIES = 2
MAX_WAIT = 10
USER_AGENT = f"TheCollector/{__version__}"

opener = urllib.request.urlopen
sleep = time.sleep


class HttpError(Exception):
    """A failed request. status is 0 when the server couldn't be reached."""

    def __init__(self, status: int, body: str = "", retry_after: int | None = None):
        super().__init__(f"HTTP {status}" if status else f"Network error: {body}")
        self.status = status
        self.body = body
        self.retry_after = retry_after


def _retry_after(headers) -> int | None:
    try:
        return int(headers.get("Retry-After"))
    except (TypeError, ValueError, AttributeError):
        return None


def request_json(method: str, url: str, *, headers: dict | None = None, params: dict | None = None,
                 form: dict | None = None, json_body: dict | None = None,
                 basic_auth: tuple[str, str] | None = None) -> dict:
    """Send a request and return the decoded JSON body ({} when empty).

    Retries 429 responses up to MAX_RETRIES times, waiting Retry-After seconds (at most MAX_WAIT).
    """
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    hdrs = {"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif json_body is not None:
        data = json.dumps(json_body).encode()
        hdrs.setdefault("Content-Type", "application/json")
    if basic_auth:
        token = base64.b64encode(f"{basic_auth[0]}:{basic_auth[1]}".encode()).decode()
        hdrs["Authorization"] = f"Basic {token}"

    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with opener(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            wait = _retry_after(e.headers)
            if e.code == 429 and attempt < MAX_RETRIES:
                sleep(min(wait if wait is not None else 2, MAX_WAIT))
                continue
            raise HttpError(e.code, body, wait) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise HttpError(0, str(getattr(e, "reason", e))) from e
        except ValueError as e:
            raise HttpError(200, "The server sent something that isn't JSON.") from e
    raise HttpError(429)  # not reached


def download(url: str, dest: Path, *, allowed_hosts: tuple[str, ...], max_bytes: int = 50_000_000) -> None:
    """Save a binary file to `dest`, refusing other hosts (after redirects) and oversized bodies.

    A partial file is deleted on any failure.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        try:
            with opener(req, timeout=TIMEOUT) as resp:
                # urllib follows redirects itself, so check where we actually ended up before saving anything.
                if urllib.parse.urlsplit(resp.geturl()).hostname not in allowed_hosts:
                    raise HttpError(0, "Download came from an unexpected address.")
                size = 0
                with open(dest, "wb") as out:
                    while chunk := resp.read(64 * 1024):
                        size += len(chunk)
                        if size > max_bytes:
                            raise HttpError(0, "Download is larger than expected.")
                        out.write(chunk)
        except HttpError:
            raise
        except urllib.error.HTTPError as e:
            raise HttpError(e.code, e.read().decode(errors="replace")) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise HttpError(0, str(getattr(e, "reason", e))) from e
        except HTTPException as e:  # e.g. IncompleteRead when the connection is cut mid-body
            raise HttpError(0, "The download was interrupted.") from e
    except BaseException:
        dest.unlink(missing_ok=True)  # whatever went wrong, never leave a partial file behind
        raise
