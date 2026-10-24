"""Thin HTTP layer: shared session, app headers, and uniform error mapping."""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import requests

from . import const
from .errors import NetworkError, UpstreamError

_LOG = logging.getLogger("ica_handla.http")


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": const.USER_AGENT,
        "x-user-agent": const.USER_AGENT,
        "Accept": "application/json",
    })
    return s


def correlation_headers() -> dict[str, str]:
    cid = str(uuid.uuid4())
    return {"X-Correlation-ID": cid, "X-Request-ID": cid}


def request(session: requests.Session, method: str, url: str, *,
            retry_202: bool = False, max_wait: float = 60.0,
            **kwargs: Any) -> requests.Response:
    """Perform a request, mapping transport failures to NetworkError.

    If ``retry_202`` is set, a 202 Accepted (ICA's "search warming up" response)
    is retried with bounded backoff. Progress goes to the logger (stderr), never
    stdout, so JSON output stays machine-safe.
    """
    headers = {**correlation_headers(), **(kwargs.pop("headers", None) or {})}
    deadline = time.monotonic() + max_wait
    delay = 1.0
    while True:
        try:
            resp = session.request(method, url, headers=headers, timeout=30, **kwargs)
        except requests.RequestException as e:  # noqa: PERF203
            raise NetworkError(f"network error talking to ICA: {e}") from e
        if retry_202 and resp.status_code == 202 and time.monotonic() < deadline:
            _LOG.info("202 Accepted, retrying in %.1fs", delay)
            time.sleep(delay)
            delay = min(delay * 1.7, 10.0)
            headers = {**correlation_headers(), **(kwargs.get("headers") or {})}
            continue
        return resp


def json_or_raise(resp: requests.Response, *, context: str = "") -> Any:
    """Return parsed JSON for 2xx, else raise an UpstreamError with detail."""
    if 200 <= resp.status_code < 300:
        if not resp.content:
            return {"status": resp.status_code}
        try:
            return resp.json()
        except ValueError:
            return {"status": resp.status_code, "text": resp.text[:500]}
    detail: dict[str, Any] = {}
    try:
        detail = resp.json()
    except ValueError:
        if resp.text:
            detail = {"text": resp.text[:500]}
    raise UpstreamError(
        f"ICA returned HTTP {resp.status_code}" + (f" for {context}" if context else ""),
        code="upstream_http", http_status=resp.status_code, details=detail or None,
    )
