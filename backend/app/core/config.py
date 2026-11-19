"""Application configuration loaded from the process environment."""

from dataclasses import dataclass
import os


_ALLOWED_ENVIRONMENTS = {"development", "test", "production"}


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings that do not contain provider or database choices yet."""

    environment: str = "development"


def load_settings() -> Settings:
    """Read and validate the settings currently needed by the API process.

    Secrets, database paths, authentication settings, and AI provider settings
    are intentionally absent until those parts of the architecture are built.
    """

    environment = os.getenv("ATLAS_ENV", "development").strip().lower()

    if environment not in _ALLOWED_ENVIRONMENTS:
        allowed = ", ".join(sorted(_ALLOWED_ENVIRONMENTS))
        raise ValueError(f"ATLAS_ENV must be one of: {allowed}.")

    return Settings(environment=environment)
