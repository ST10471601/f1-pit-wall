import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_CONFIG = REPO_ROOT / "config" / "settings.yaml"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the developer's PITWALL_* variables and .env file out of every test."""
    for name in list(os.environ):
        if name.startswith("PITWALL_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
