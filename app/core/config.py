"""All configuration comes from environment variables (.env). No secrets in the frontend."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "GPPSL Platform"
    # Use "mongomock://" to run against an in-memory fake database (tests, quick demos).
    mongo_url: str = "mongodb://localhost:27017"
    db_name: str = "gppsl"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    login_rate_limit_per_minute: int = 5

    demo_mode: bool = True  # enables one-click demo logins. Set false in production.
    timezone: str = "Africa/Lagos"
    cors_origins: str = "*"

    # External services. Every one has a labelled local/mock fallback.
    mistral_api_key: str = ""
    mistral_model: str = "ministral-8b-latest"
    mistral_embedding_model: str = "mistral-embed"
    google_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"
    gemini_embedding_model: str = "models/text-embedding-004"
    cloudinary_url: str = ""
    upload_dir: str = "uploads"
    public_base_url: str = "https://gppsl-be.vercel.app"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = "accounts@gppsl.example"
    brevo_api_key: str = ""
    resend_api_key: str = ""

    face_threshold: float = 0.6
    enable_scheduler: bool = True

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def use_mock_db(self) -> bool:
        return self.mongo_url.startswith("mongomock")


@lru_cache
def get_settings() -> Settings:
    return Settings()
