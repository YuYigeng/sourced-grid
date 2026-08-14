from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOURCEDGRID_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    database_url: str | None = None
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    worker_poll_seconds: float = 0.6
    worker_lease_seconds: int = 90
    worker_concurrency: int = 5
    max_http_bytes: int = 2_000_000
    http_timeout_seconds: float = 20.0
    default_openai_base_url: str = "https://api.openai.com/v1"
    default_openai_model: str = "gpt-5-mini"
    default_anthropic_model: str = "claude-sonnet-4-5"

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'sourcedgrid.db').resolve()}"

    @property
    def database_path(self) -> Path:
        if self.database_url and self.database_url.startswith("sqlite:///"):
            return Path(self.database_url.removeprefix("sqlite:///"))
        return self.data_dir / "sourcedgrid.db"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def master_key_path(self) -> Path:
        return self.data_dir / "master.key"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    return settings
