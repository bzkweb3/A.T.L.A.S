"""Centralized, dependency-light application configuration."""

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    app_name: str = "A.T.L.A.S."
    app_version: str = "0.1.0"
    environment: str = "development"
    log_level: str = "INFO"

    @classmethod
    def from_environment(cls) -> "Settings":
        environment = os.getenv("ATLAS_ENV", "development").strip().lower()
        if environment not in {"development", "test", "production"}:
            raise ValueError("ATLAS_ENV must be development, test, or production.")

        log_level = os.getenv("ATLAS_LOG_LEVEL", "INFO").strip().upper()
        if log_level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("ATLAS_LOG_LEVEL must be CRITICAL, ERROR, WARNING, INFO, or DEBUG.")

        return cls(environment=environment, log_level=log_level)


settings = Settings.from_environment()
