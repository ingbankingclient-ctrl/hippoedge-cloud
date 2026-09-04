from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "HippoEdge"
    environment: str = "development"
    database_url: str = "sqlite:///./hippoedge.db"
    provider: str = "demo"  # demo | pmu | turfbzh
    pmu_base_url: str = "https://online.turfinfo.api.pmu.fr/rest/client/1"
    letrot_base_url: str = "https://www.letrot.com"
    france_galop_base_url: str = "https://www.france-galop.com"
    geny_base_url: str = "https://www.geny.com"
    geny_history_enabled: bool = True
    official_history_enabled: bool = True
    history_request_interval_seconds: float = 0.35
    # 0 = no local career-row cap: keep every performance published by the source.
    history_max_rows: int = 0
    # Bound only in-memory provider caches; persisted histories remain complete.
    history_cache_size: int = 16
    history_course_cache_size: int = 128
    history_directory_cache_size: int = 4
    history_course_batch_size: int = 120
    # Failed historical-race lookups are retried on later maintenance passes instead of being abandoned forever.
    history_course_retry_cooldown_seconds: int = 900
    selection_min_history_rows: int = 3
    selection_min_field_coverage_percent: int = 70
    turfbzh_api_key: str | None = None
    turfbzh_base_url: str = "https://www.turf.bzh/api/v1"
    timezone: str = "Europe/Paris"
    refresh_seconds: int = 900
    auto_lock_minutes_before: int = 2
    methodology_version: str = "2026.09.04-v6.9.1-complete"
    cors_origins: str = "*"

    model_config = SettingsConfigDict(
        env_file=(Path(__file__).resolve().parents[2] / ".env"),
        env_prefix="HIPPOEDGE_",
        extra="ignore",
    )

    @property
    def cors_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
