"""Application configuration loaded from environment variables and .env."""

from dataclasses import dataclass
import os

from dotenv import load_dotenv

_ALLOWED_ENVIRONMENTS = {"development", "test", "production"}
_ALLOWED_PROVIDERS = {"gemini", "openai"}


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated runtime settings; secrets are never returned by API routes."""

    environment: str = "development"
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    ai_provider: str = "gemini"
    ai_model: str = "gemini-2.5-flash"


def load_settings() -> Settings:
    """Load local .env values and validate runtime configuration."""

    load_dotenv()
    environment = os.getenv("ATLAS_ENV", "development").strip().lower()
    if environment not in _ALLOWED_ENVIRONMENTS:
        allowed = ", ".join(sorted(_ALLOWED_ENVIRONMENTS))
        raise ValueError(f"ATLAS_ENV must be one of: {allowed}.")

    ai_provider = os.getenv("ATLAS_AI_PROVIDER", "gemini").strip().lower()
    if ai_provider not in _ALLOWED_PROVIDERS:
        allowed = ", ".join(sorted(_ALLOWED_PROVIDERS))
        raise ValueError(f"ATLAS_AI_PROVIDER must be one of: {allowed}.")

    default_model = "gemini-2.5-flash" if ai_provider == "gemini" else "gpt-5.5"
    return Settings(
        environment=environment,
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip() or None,
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip() or None,
        ai_provider=ai_provider,
        ai_model=os.getenv("ATLAS_AI_MODEL", default_model).strip() or default_model,
    )
