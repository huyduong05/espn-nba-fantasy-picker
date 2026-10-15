"""Small, dependency-free HTTP client with bounded retries and rate limiting."""

from __future__ import annotations

import json
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.message import Message
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi


class AcquisitionError(RuntimeError):
    """An actionable acquisition failure that is safe to show to the user."""


@dataclass(frozen=True)
class HttpResponse:
    url: str
    status: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AcquisitionError(f"Expected JSON from {self.url}") from error


class HttpTransport(Protocol):
    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse: ...


class HttpClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 30,
        max_attempts: int = 4,
        minimum_interval_seconds: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.minimum_interval_seconds = minimum_interval_seconds
        self._sleep = sleep
        self._clock = clock
        self._ssl_context = ssl_context or ssl.create_default_context(cafile=certifi.where())
        self._last_request_at: float | None = None

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        full_url = _url_with_query(url, params)
        request_headers = {
            "Accept": "application/json, application/octet-stream;q=0.9, */*;q=0.8",
            "User-Agent": "espn-nba-fantasy-picker/0.1 (+local personal project)",
            **(headers or {}),
        }

        for attempt in range(1, self.max_attempts + 1):
            self._respect_rate_limit()
            request = Request(full_url, headers=request_headers, method="GET")
            try:
                with urlopen(  # noqa: S310
                    request,
                    timeout=self.timeout_seconds,
                    context=self._ssl_context,
                ) as response:
                    self._last_request_at = self._clock()
                    response_headers = _headers_to_dict(response.headers)
                    return HttpResponse(
                        url=full_url,
                        status=response.status,
                        headers=response_headers,
                        body=response.read(),
                    )
            except HTTPError as error:
                self._last_request_at = self._clock()
                if error.code not in {429, 500, 502, 503, 504} or attempt == self.max_attempts:
                    raise AcquisitionError(_http_error_message(error, full_url)) from error
                self._sleep(_retry_delay(attempt, error.headers))
            except (TimeoutError, URLError) as error:
                self._last_request_at = self._clock()
                if attempt == self.max_attempts:
                    raise AcquisitionError(
                        f"Failed to download {full_url} after {self.max_attempts} attempts: {error}"
                    ) from error
                self._sleep(min(2 ** (attempt - 1), 8))

        raise AssertionError("retry loop terminated unexpectedly")

    def _respect_rate_limit(self) -> None:
        if self._last_request_at is None:
            return
        remaining = self.minimum_interval_seconds - (self._clock() - self._last_request_at)
        if remaining > 0:
            self._sleep(remaining)


def _url_with_query(url: str, params: Mapping[str, str | int] | None) -> str:
    if not params:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def _headers_to_dict(headers: Message) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


def _retry_delay(attempt: int, headers: Message | None) -> float:
    if headers is not None:
        retry_after = headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return min(float(retry_after), 30)
    return float(min(2 ** (attempt - 1), 8))


def _http_error_message(error: HTTPError, url: str) -> str:
    if error.code == 401:
        return f"Unauthorized request to {url}; check the configured API key"
    if error.code == 403:
        return f"Access denied for {url}; check the API subscription tier and rate limit"
    if error.code == 429:
        return f"Rate limit remained exceeded for {url} after retries"
    return f"HTTP {error.code} while downloading {url}"
