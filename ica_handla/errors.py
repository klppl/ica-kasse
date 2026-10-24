"""Structured, agent-friendly errors and exit codes.

Successful commands print ``{"ok": true, "data": ...}`` on stdout; failures
print ``{"error", "code", "http_status?", "details?"}`` on stderr and exit with
a stable non-zero code.
"""
from __future__ import annotations

import json
import sys
from typing import Any

# Exit codes (stable contract for scripting)
SUCCESS = 0
USAGE = 1
AUTH = 2
UPSTREAM = 3
NETWORK = 4


class IcaError(Exception):
    """Base class carrying an exit code + machine-readable error code."""

    exit_code = UPSTREAM
    code = "error"

    def __init__(self, message: str, *, code: str | None = None,
                 http_status: int | None = None, details: dict | None = None,
                 exit_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if exit_code is not None:
            self.exit_code = exit_code
        self.http_status = http_status
        self.details = details


class UsageError(IcaError):
    exit_code = USAGE
    code = "usage"


class AuthError(IcaError):
    exit_code = AUTH
    code = "auth_failed"


class UpstreamError(IcaError):
    exit_code = UPSTREAM
    code = "upstream_http"


class NetworkError(IcaError):
    exit_code = NETWORK
    code = "network_error"


class NotFoundError(IcaError):
    exit_code = UPSTREAM
    code = "not_found"


def success_payload(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def print_json_error(err: IcaError) -> None:
    payload: dict[str, Any] = {"error": err.message, "code": err.code}
    if err.http_status is not None:
        payload["http_status"] = err.http_status
    if err.details:
        payload["details"] = err.details
    sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
