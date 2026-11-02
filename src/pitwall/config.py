import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

DEFAULT_CONFIG_FILE = Path("config/settings.yaml")
CONFIG_FILE_ENV_VAR = "PITWALL_CONFIG_FILE"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ApiSettings(_Section):
    base_url: str
    timeout_seconds: float = Field(gt=0)
    max_retries: int = Field(ge=0)
    retry_backoff_seconds: float = Field(gt=0)
    retry_backoff_max_seconds: float = Field(gt=0)
    requests_per_second: int = Field(gt=0)
    requests_per_minute: int = Field(gt=0)


class RunSettings(_Section):
    first_season: int = Field(ge=2023)
    settle_delay_hours: int = Field(ge=0)
    reprocess_window_days: int = Field(ge=0)
    serving_snapshots_kept: int = Field(ge=1)


class DuckDBSettings(_Section):
    threads: int = Field(gt=0)
    memory_limit: str


class Settings(BaseSettings):
    """YAML values, overridden by PITWALL_* environment variables (PITWALL_API__TIMEOUT_SECONDS)."""

    model_config = SettingsConfigDict(
        env_prefix="PITWALL_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="forbid",
        frozen=True,
    )

    data_dir: Path
    dbt_project_dir: Path
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
    api: ApiSettings
    run: RunSettings
    duckdb: DuckDBSettings
    # Secret: set through the environment only, never in the YAML file.
    discord_webhook_url: SecretStr | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # YAML values arrive as init kwargs, so they must rank below the environment.
        return env_settings, dotenv_settings, init_settings

    @property
    def bronze_dir(self) -> Path:
        return self.data_dir / "bronze"

    @property
    def silver_dir(self) -> Path:
        return self.data_dir / "silver"

    @property
    def quarantine_dir(self) -> Path:
        return self.silver_dir / "_quarantine"

    @property
    def serving_dir(self) -> Path:
        return self.data_dir / "serving"

    @property
    def ops_db(self) -> Path:
        return self.data_dir / "ops.duckdb"

    @property
    def warehouse_db(self) -> Path:
        return self.data_dir / "warehouse.duckdb"

    @property
    def duckdb_temp_dir(self) -> Path:
        return self.data_dir / "tmp"


class ConfigError(Exception):
    pass


def load_settings(config_file: Path | None = None) -> Settings:
    path = config_file or Path(os.environ.get(CONFIG_FILE_ENV_VAR, DEFAULT_CONFIG_FILE))
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")

    values: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(values, dict):
        raise ConfigError(f"config file must contain a mapping at the top level: {path}")
    return Settings(**values)
