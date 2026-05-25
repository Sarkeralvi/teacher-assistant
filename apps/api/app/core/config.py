from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    app_name: str = Field(default="Teacher Assistant", alias="APP_NAME")
    database_url: str = Field(
        default="postgresql+psycopg://teacher_assistant:teacher_assistant_dev_password@localhost:5432/teacher_assistant",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    rq_default_queue: str = Field(default="teacher-assistant-default", alias="RQ_DEFAULT_QUEUE")
    storage_backend: str = Field(default="local", alias="STORAGE_BACKEND")
    local_storage_root: str = Field(default="/data", alias="LOCAL_STORAGE_ROOT")
    uploads_dir: str = Field(default="/data/uploads", alias="UPLOADS_DIR")
    artifacts_dir: str = Field(default="/data/artifacts", alias="ARTIFACTS_DIR")
    brain_provider: str = Field(default="mock", alias="BRAIN_PROVIDER")
    brain_allow_real_providers: bool = Field(default=False, alias="BRAIN_ALLOW_REAL_PROVIDERS")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="", alias="OPENAI_MODEL")
    openai_base_url: str = Field(default="", alias="OPENAI_BASE_URL")
    openai_timeout_seconds: float = Field(default=30.0, alias="OPENAI_TIMEOUT_SECONDS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
