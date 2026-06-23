from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # OpenAI
    OPENAI_API_KEY: str

    # Postgres
    POSTGRES_CONNECTION_STRING: str
    APP_DB_CONNECTION_STRING: str | None = None

    # App
    PDF_MOUNT_PATH: str = "/app/pdfs"
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"
    WORKER_POLL_INTERVAL_SECONDS: int = 5

    model_config = {
        "env_file": (".env", "../.env"),
        "case_sensitive": True,
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore
