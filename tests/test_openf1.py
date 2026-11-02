import json
import logging
from collections.abc import Iterator

import pytest
import requests
import responses
from responses import matchers

from pitwall.ingestion.openf1 import (
    OpenF1Client,
    OpenF1HTTPError,
    OpenF1PayloadError,
    OpenF1UnavailableError,
)
from tests.conftest import API_SETTINGS, OPENF1_URL, FakeClock

SESSIONS_URL = f"{OPENF1_URL}/sessions"
NO_RESULTS = {"detail": "No results found."}


@pytest.fixture
def client(clock: FakeClock) -> Iterator[OpenF1Client]:
    with OpenF1Client(API_SETTINGS, clock=clock, sleep=clock.sleep) as openf1:
        yield openf1


def test_returns_records_and_the_body_exactly_as_received(
    api: responses.RequestsMock, client: OpenF1Client
) -> None:
    body = b'[{"session_key": 9472, "session_name": "Race"}]'
    api.get(
        SESSIONS_URL,
        body=body,
        content_type="application/json",
        match=[matchers.query_param_matcher({"year": "2024", "session_name": "Race"})],
    )

    result = client.get("sessions", {"year": 2024, "session_name": "Race"})

    assert result.records == [{"session_key": 9472, "session_name": "Race"}]
    assert result.body == body
    assert result.status_code == 200
    assert result.attempts == 1
    assert result.url.startswith(SESSIONS_URL + "?")
    assert api.calls[0].request.headers["User-Agent"].startswith("pitwall/")


def test_no_results_404_is_an_empty_result(
    api: responses.RequestsMock, client: OpenF1Client
) -> None:
    api.get(SESSIONS_URL, json=NO_RESULTS, status=404)

    result = client.get("sessions", {"session_key": 1})

    assert result.records == []
    assert result.status_code == 404
    assert json.loads(result.body) == NO_RESULTS


def test_empty_list_is_an_empty_result(api: responses.RequestsMock, client: OpenF1Client) -> None:
    api.get(SESSIONS_URL, json=[])

    assert client.get("sessions", {}).records == []


@pytest.mark.parametrize(
    ("status", "body"),
    [(404, {"detail": "Not Found"}), (400, {"detail": "bad filter"}), (401, {})],
)
def test_client_errors_fail_without_retrying(
    api: responses.RequestsMock,
    client: OpenF1Client,
    clock: FakeClock,
    status: int,
    body: dict[str, str],
) -> None:
    api.get(SESSIONS_URL, json=body, status=status)

    with pytest.raises(OpenF1HTTPError) as exc:
        client.get("sessions", {"session_key": 9472})

    assert exc.value.status_code == status
    assert exc.value.attempts == 1
    assert exc.value.params == {"session_key": 9472}
    assert len(api.calls) == 1
    assert clock.sleeps == []


def test_429_is_retried_honouring_retry_after(
    api: responses.RequestsMock, client: OpenF1Client, clock: FakeClock
) -> None:
    api.get(SESSIONS_URL, status=429, headers={"Retry-After": "3"})
    api.get(SESSIONS_URL, json=[{"session_key": 9472}])

    result = client.get("sessions", {})

    assert result.attempts == 2
    assert clock.sleeps == [3.0]


def test_retry_after_is_capped_to_keep_runs_bounded(
    api: responses.RequestsMock, client: OpenF1Client, clock: FakeClock
) -> None:
    api.get(SESSIONS_URL, status=429, headers={"Retry-After": "3600"})
    api.get(SESSIONS_URL, json=[])

    client.get("sessions", {})

    assert clock.sleeps == [5.0]


def test_server_errors_back_off_exponentially_then_raise(
    api: responses.RequestsMock, client: OpenF1Client, clock: FakeClock
) -> None:
    api.get(SESSIONS_URL, status=503, body=b"unavailable")

    with pytest.raises(OpenF1HTTPError) as exc:
        client.get("sessions", {})

    assert exc.value.status_code == 503
    assert exc.value.body == b"unavailable"
    assert exc.value.attempts == 4
    assert len(api.calls) == 4
    assert clock.sleeps == [2.0, 4.0, 5.0]


def test_server_error_then_success_recovers(
    api: responses.RequestsMock, client: OpenF1Client
) -> None:
    api.get(SESSIONS_URL, status=500)
    api.get(SESSIONS_URL, status=502)
    api.get(SESSIONS_URL, json=[{"session_key": 9472}])

    assert client.get("sessions", {}).attempts == 3


def test_timeout_then_success_recovers(
    api: responses.RequestsMock, client: OpenF1Client, clock: FakeClock
) -> None:
    api.get(SESSIONS_URL, body=requests.ReadTimeout())
    api.get(SESSIONS_URL, json=[])

    assert client.get("sessions", {}).attempts == 2
    assert clock.sleeps == [2.0]


def test_persistent_connection_errors_raise_unavailable(
    api: responses.RequestsMock, client: OpenF1Client
) -> None:
    api.get(SESSIONS_URL, body=requests.ConnectionError())

    with pytest.raises(OpenF1UnavailableError, match="ConnectionError") as exc:
        client.get("sessions", {})

    assert exc.value.attempts == 4


@pytest.mark.parametrize(
    "body", [b'[{"session_key": 94', b'{"session_key": 9472}', b"[1, 2]"], ids=str
)
def test_malformed_payload_fails_without_retrying_and_keeps_the_body(
    api: responses.RequestsMock, client: OpenF1Client, body: bytes
) -> None:
    api.get(SESSIONS_URL, body=body, content_type="application/json")

    with pytest.raises(OpenF1PayloadError) as exc:
        client.get("sessions", {})

    assert exc.value.body == body
    assert len(api.calls) == 1


def test_retries_also_wait_for_the_configured_rate_limit(
    api: responses.RequestsMock, clock: FakeClock
) -> None:
    api.get(SESSIONS_URL, status=500)
    api.get(SESSIONS_URL, json=[])
    one_per_minute = API_SETTINGS.model_copy(update={"requests_per_minute": 1})

    with OpenF1Client(one_per_minute, clock=clock, sleep=clock.sleep) as client:
        client.get("sessions", {})

    # 2 s backoff, then the limiter holds the retry until 60 s after the first call.
    assert clock.sleeps == [2.0, 58.0]


def test_logs_each_fetch_and_retry(
    api: responses.RequestsMock, client: OpenF1Client, caplog: pytest.LogCaptureFixture
) -> None:
    api.get(SESSIONS_URL, status=500)
    api.get(SESSIONS_URL, json=[{"session_key": 9472}])

    with caplog.at_level(logging.INFO, logger="pitwall.ingestion.openf1"):
        client.get("sessions", {"year": 2024})

    retry, fetched = caplog.records
    assert retry.getMessage() == "retrying"
    assert retry.__dict__["reason"] == "HTTP 500"
    assert fetched.getMessage() == "fetched"
    assert fetched.__dict__["records"] == 1
    assert fetched.__dict__["params"] == {"year": 2024}
