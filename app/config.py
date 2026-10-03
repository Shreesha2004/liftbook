from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "dev-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    SECRET_KEY: str = DEV_SECRET_KEY
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    ENVIRONMENT: Literal["development", "production", "test"] = "development"
    # When true, startup creates the demo account with generated history if it is empty.
    SEED_DEMO_DATA: bool = False

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_scheme(cls, url: str) -> str:
        # Render/Heroku hand out "postgres://" URLs, which SQLAlchemy 2 rejects.
        if url.startswith("postgres://"):
            return "postgresql://" + url.removeprefix("postgres://")
        return url

    @model_validator(mode="after")
    def _require_real_secret_in_production(self) -> "Settings":
        if self.ENVIRONMENT == "production" and self.SECRET_KEY == DEV_SECRET_KEY:
            raise ValueError("SECRET_KEY must be set when ENVIRONMENT=production")
        return self

    @property
    def cookie_secure(self) -> bool:
        return self.ENVIRONMENT == "production"


settings = Settings()
