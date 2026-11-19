"""Application configuration loaded from environment variables and .env."""

from dataclasses import dataclass
import os

from dotenv import load_dotenv

_ALLOWED_ENVIRONMENTS = {"development", "test", "production"}


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated runtime settings; secrets are never returned by API routes."""

    environment: str = "development"
    openai_api_key: str | None = None
    ai_model: str = "gpt-5.5"


def load_settings() -> Settings:
    """Load local .env values and validate runtime configuration."""

    load_dotenv()
    environment = os.getenv("ATLAS_ENV", "development").strip().lower()
    if environment not in _ALLOWED_ENVIRONMENTS:
        allowed = ", ".join(sorted(_ALLOWED_ENVIRONMENTS))
        raise ValueError(f"ATLAS_ENV must be one of: {allowed}.")

    return Settings(
        environment=environment,
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip() or None,
        ai_model=os.getenv("ATLAS_AI_MODEL", "gpt-5.5").strip() or "gpt-5.5",
    )
