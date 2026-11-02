import os
from collections.abc import Iterator
from pathlib import Path

import pytest
import responses

from pitwall.config import ApiSettings

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_CONFIG = REPO_ROOT / "config" / "settings.yaml"

OPENF1_URL = "https://api.openf1.org/v1"
# Small retry waits and loose rate limits; tests that need a real limit set their own.
API_SETTINGS = ApiSettings(
    base_url=OPENF1_URL,
    timeout_seconds=5,
    max_retries=3,
    retry_backoff_seconds=2,
    retry_backoff_max_seconds=5,
    requests_per_second=100,
    requests_per_minute=1000,
)


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the developer's PITWALL_* variables and .env file out of every test."""
    for name in list(os.environ):
        if name.startswith("PITWALL_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


class FakeClock:
    """Monotonic clock that only moves when something sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    """Mocked HTTP; any request that isn't registered fails, as does any unused registration."""
    with responses.RequestsMock() as mock:
        yield mock
