import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib.metadata import version
from typing import Any, Self

import requests

from pitwall.config import ApiSettings
from pitwall.ingestion.rate_limit import RateLimiter

log = logging.getLogger(__name__)

Params = Mapping[str, str | int]

# OpenF1 answers an empty result with this 404 rather than an empty list. Unknown endpoints get
# the same response, so callers must only request endpoints that exist.
_NO_RESULTS = {"detail": "No results found."}
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_USER_AGENT = f"pitwall/{version('pitwall')} (+https://github.com/ST10471601/f1-pit-wall)"


@dataclass(frozen=True)
class ApiResponse:
    """One OpenF1 response: the body exactly as received plus its parsed records."""

    endpoint: str
    params: dict[str, str | int]
    url: str
    status_code: int
    body: bytes
    records: list[dict[str, Any]]
    attempts: int


class OpenF1Error(Exception):
    """Base class for OpenF1 failures."""

    def __init__(self, message: str, endpoint: str, params: Params, attempts: int) -> None:
        super().__init__(f"{message} ({endpoint} {dict(params)}, attempts={attempts})")
        self.endpoint = endpoint
        self.params = dict(params)
        self.attempts = attempts


class OpenF1HTTPError(OpenF1Error):
    """A status that is not retried, or a retryable one that outlasted max_retries."""

    def __init__(
        self, status_code: int, body: bytes, endpoint: str, params: Params, attempts: int
    ) -> None:
        super().__init__(f"HTTP {status_code}", endpoint, params, attempts)
        self.status_code = status_code
        self.body = body


class OpenF1UnavailableError(OpenF1Error):
    """Timeouts or connection errors that outlasted max_retries."""


class OpenF1PayloadError(OpenF1Error):
    """A successful response whose body is not a JSON list of objects."""

    def __init__(
        self, message: str, body: bytes, endpoint: str, params: Params, attempts: int
    ) -> None:
        super().__init__(message, endpoint, params, attempts)
        self.body = body


class OpenF1Client:
    """Rate-limited OpenF1 client with retries; share one instance across a run."""

    def __init__(
        self,
        settings: ApiSettings,
        *,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._session = session or requests.Session()
        self._session.headers["User-Agent"] = _USER_AGENT
        self._limiter = RateLimiter(
            [(settings.requests_per_second, 1.0), (settings.requests_per_minute, 60.0)],
            clock=clock,
            sleep=sleep,
        )
        self._sleep = sleep

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    def get(self, endpoint: str, params: Params) -> ApiResponse:
        """Fetch one endpoint; a 'no results' 404 comes back as an empty record list."""
        url = f"{self._settings.base_url.rstrip('/')}/{endpoint}"
        max_attempts = self._settings.max_retries + 1
        attempt = 0
        while True:
            attempt += 1
            self._limiter.wait()
            started = time.monotonic()
            try:
                response = self._session.get(
                    url, params=params, timeout=self._settings.timeout_seconds
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt == max_attempts:
                    raise OpenF1UnavailableError(
                        type(exc).__name__, endpoint, params, attempt
                    ) from exc
                self._back_off(attempt, endpoint, type(exc).__name__, retry_after=None)
                continue

            if response.status_code in _RETRYABLE_STATUS and attempt < max_attempts:
                self._back_off(
                    attempt, endpoint, f"HTTP {response.status_code}", _retry_after(response)
                )
                continue

            records = _parse_records(response, endpoint, params, attempt)
            log.info(
                "fetched",
                extra={
                    "endpoint": endpoint,
                    "params": dict(params),
                    "status_code": response.status_code,
                    "records": len(records),
                    "attempts": attempt,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                },
            )
            return ApiResponse(
                endpoint=endpoint,
                params=dict(params),
                url=response.url,
                status_code=response.status_code,
                body=response.content,
                records=records,
                attempts=attempt,
            )

    def _back_off(
        self, attempt: int, endpoint: str, reason: str, retry_after: float | None
    ) -> None:
        # One sequential client, so plain exponential backoff; jitter only helps when many
        # clients retry at once. The cap keeps a scheduled run bounded even if Retry-After is long.
        delay = self._settings.retry_backoff_seconds * 2 ** (attempt - 1)
        if retry_after is not None:
            delay = max(delay, retry_after)
        delay = min(delay, self._settings.retry_backoff_max_seconds)
        log.warning(
            "retrying",
            extra={
                "endpoint": endpoint,
                "reason": reason,
                "attempt": attempt,
                "delay_seconds": delay,
            },
        )
        self._sleep(delay)


def _parse_records(
    response: requests.Response, endpoint: str, params: Params, attempt: int
) -> list[dict[str, Any]]:
    if response.status_code == 404 and _json_or_none(response) == _NO_RESULTS:
        return []
    if not response.ok:
        raise OpenF1HTTPError(response.status_code, response.content, endpoint, params, attempt)

    payload = _json_or_none(response)
    if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
        raise OpenF1PayloadError(
            "body is not a JSON list of objects", response.content, endpoint, params, attempt
        )
    return payload


def _json_or_none(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _retry_after(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    return float(value) if value.isdigit() else None
