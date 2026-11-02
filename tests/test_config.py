from pathlib import Path

import pytest
from pydantic import ValidationError

from pitwall.config import ConfigError, load_settings
from tests.conftest import REPO_CONFIG


def test_repo_config_loads_with_derived_paths() -> None:
    settings = load_settings(REPO_CONFIG)

    assert settings.api.requests_per_second == 3
    assert settings.api.requests_per_minute == 30
    assert settings.run.settle_delay_hours == 6
    assert settings.bronze_dir == Path("data/bronze")
    assert settings.quarantine_dir == Path("data/silver/_quarantine")
    assert settings.serving_dir == Path("data/serving")
    assert settings.ops_db == Path("data/ops.duckdb")
    assert settings.warehouse_db == Path("data/warehouse.duckdb")
    assert settings.duckdb_temp_dir == Path("data/tmp")
    assert settings.dbt_project_dir == Path("dbt")
    assert settings.discord_webhook_url is None


def test_env_var_overrides_yaml_and_keeps_sibling_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PITWALL_API__TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("PITWALL_DATA_DIR", "D:/pitwall-data")

    settings = load_settings(REPO_CONFIG)

    assert settings.api.timeout_seconds == 5
    assert settings.api.requests_per_second == 3
    assert settings.warehouse_db == Path("D:/pitwall-data/warehouse.duckdb")


def test_dotenv_file_overrides_yaml(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("PITWALL_LOG_LEVEL=DEBUG\n", encoding="utf-8")

    assert load_settings(REPO_CONFIG).log_level == "DEBUG"


def test_config_file_can_be_set_by_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PITWALL_CONFIG_FILE", str(REPO_CONFIG))

    assert load_settings().api.base_url == "https://api.openf1.org/v1"


def test_misspelt_key_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "settings.yaml"
    text = REPO_CONFIG.read_text(encoding="utf-8").replace("max_retries", "max_retry")
    config.write_text(text, encoding="utf-8")

    with pytest.raises(ValidationError, match="max_retry"):
        load_settings(config)


def test_invalid_value_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PITWALL_API__REQUESTS_PER_SECOND", "0")

    with pytest.raises(ValidationError, match="requests_per_second"):
        load_settings(REPO_CONFIG)


def test_non_mapping_file_raises(tmp_path: Path) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text("- just\n- a list\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="mapping"):
        load_settings(config)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "missing.yaml")


def test_secret_is_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://discord.com/api/webhooks/123/token"
    monkeypatch.setenv("PITWALL_DISCORD_WEBHOOK_URL", url)

    settings = load_settings(REPO_CONFIG)

    assert settings.discord_webhook_url is not None
    assert settings.discord_webhook_url.get_secret_value() == url
    assert url not in repr(settings)
