"""Tiny stdlib HTTP client with gzip and structured API errors."""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

REDACTED = "***"


class ApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        retry_after_ms: int | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.retry_after_ms = retry_after_ms
        self.body = body


def _decode(raw: bytes, encoding: str | None) -> Any:
    if encoding == "gzip" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    text = raw.decode("utf-8", errors="replace")
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _error_from_payload(payload: Any, status: int | None) -> ApiError:
    code = None
    message = None
    retry_after = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            message = error.get("message")
            retry_after = error.get("retry_after_ms")
        message = message or payload.get("message") or payload.get("detail")
        code = code or payload.get("code")
        retry_after = retry_after or payload.get("retry_after_ms")
    if isinstance(message, (list, dict)):
        message = json.dumps(message, ensure_ascii=False)
    text = str(message) if message else f"HTTP {status}"
    lowered = text.lower()
    if code is None:
        if "too frequent" in lowered:
            code = "too_frequent"
        elif "apikey" in lowered or "api key" in lowered or status in (401, 403):
            code = "auth_error"
        elif "vip" in lowered:
            code = "vip_required"
    return ApiError(text, status=status, code=code, retry_after_ms=retry_after, body=payload)


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: Any = None,
    timeout: float = 30,
) -> Any:
    data = None
    request_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request_headers.setdefault("Accept-Encoding", "gzip")
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _decode(response.read(), response.headers.get("Content-Encoding"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        parsed = _decode(raw, exc.headers.get("Content-Encoding") if exc.headers else None)
        raise _error_from_payload(parsed, exc.code) from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"network error: {exc.reason}") from exc


def get_json(url: str, *, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None, timeout: float = 30) -> Any:
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{url}?{query}"
    return request_json("GET", url, headers=headers, timeout=timeout)


def post_json(url: str, payload: Any, *, headers: dict[str, str] | None = None, timeout: float = 30) -> Any:
    return request_json("POST", url, headers=headers, payload=payload, timeout=timeout)


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


class RateLimiter:
    """Monotonic per-endpoint delay, with explicit retry support."""

    def __init__(self, seconds: float) -> None:
        self.seconds = max(0.0, seconds)
        self._last = 0.0

    def wait(self, extra: float = 0.0) -> None:
        if self.seconds <= 0 and extra <= 0:
            return
        now = time.monotonic()
        delay = max(self.seconds, extra) - (now - self._last)
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()

    def handle_error(self, error: ApiError) -> None:
        if error.retry_after_ms:
            self.wait(error.retry_after_ms / 1000.0)
        elif error.code == "too_frequent":
            self.wait(self.seconds)
