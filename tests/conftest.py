import gzip
import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
import responses

from pitwall.config import ApiSettings

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_CONFIG = REPO_ROOT / "config" / "settings.yaml"

# Mexico City 2023 race: a VSC, a safety car and a red flag. Payloads are gzipped to stay small.
FIXTURE_BRONZE = REPO_ROOT / "tests" / "fixtures" / "bronze"
FIXTURE_SESSION_KEY = 9181
FIXTURE_RUN_ID = "20261102T135323Z-7defa8"

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


def unpack_fixture(bronze_dir: Path) -> None:
    """Copy the fixture race into a bronze directory as the pipeline wrote it."""
    for packed in FIXTURE_BRONZE.rglob("payload.json.gz"):
        target = bronze_dir / packed.parent.relative_to(FIXTURE_BRONZE)
        target.mkdir(parents=True, exist_ok=True)
        (target / "payload.json").write_bytes(gzip.decompress(packed.read_bytes()))
        shutil.copyfile(packed.with_name("metadata.json"), target / "metadata.json")


@pytest.fixture
def repo_dbt_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point settings at the repo's dbt project; tests run from a temporary directory."""
    monkeypatch.setenv("PITWALL_DBT_PROJECT_DIR", str(REPO_ROOT / "dbt"))
