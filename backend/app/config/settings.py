import os
from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings

# Proactively load env files to ensure any imported client library has access to credentials immediately
for env_path in [Path(".env"), Path("../.env")]:
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if not os.environ.get(k):
                        os.environ[k] = v



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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        import os
        if self.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = self.OPENAI_API_KEY


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore
