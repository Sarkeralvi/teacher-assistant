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
    answer_region_suggestion_provider: str = Field(
        default="mock", alias="ANSWER_REGION_SUGGESTION_PROVIDER"
    )
    codex_answer_region_suggestions_enabled: bool = Field(
        default=False, alias="CODEX_ANSWER_REGION_SUGGESTIONS_ENABLED"
    )
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_MODEL")
    gemini_image_input_enabled: bool = Field(
        default=False, alias="GEMINI_IMAGE_INPUT_ENABLED"
    )
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="", alias="OPENAI_MODEL")
    openai_base_url: str = Field(default="", alias="OPENAI_BASE_URL")
    openai_image_input_enabled: bool = Field(
        default=False, alias="OPENAI_IMAGE_INPUT_ENABLED"
    )
    openai_timeout_seconds: float = Field(default=30.0, alias="OPENAI_TIMEOUT_SECONDS")
    jwt_secret_key: str = Field(default="dev-only-change-me", alias="JWT_SECRET_KEY")
    jwt_expire_minutes: int = Field(default=480, alias="JWT_EXPIRE_MINUTES")
    codex_cli_command: str = Field(default="codex", alias="CODEX_CLI_COMMAND")
    codex_cli_model: str = Field(default="gpt-5.5", alias="CODEX_CLI_MODEL")
    codex_cli_timeout_seconds: float = Field(
        default=300.0, alias="CODEX_CLI_TIMEOUT_SECONDS"
    )
    codex_cli_sandbox: str = Field(default="read-only", alias="CODEX_CLI_SANDBOX")
    codex_cli_approval_policy: str = Field(
        default="never", alias="CODEX_CLI_APPROVAL_POLICY"
    )
    codex_cli_use_json: bool = Field(default=True, alias="CODEX_CLI_USE_JSON")
    codex_cli_output_last_message: bool = Field(
        default=True, alias="CODEX_CLI_OUTPUT_LAST_MESSAGE"
    )
    codex_cli_image_input_enabled: bool = Field(
        default=False, alias="CODEX_CLI_IMAGE_INPUT_ENABLED"
    )
    codex_cli_workdir: str = Field(
        default="/home/newton/teacher-assistant", alias="CODEX_CLI_WORKDIR"
    )
    codex_cli_skip_git_repo_check: bool = Field(
        default=False, alias="CODEX_CLI_SKIP_GIT_REPO_CHECK"
    )
    question_import_provider: str = Field(default="mock", alias="QUESTION_IMPORT_PROVIDER")
    codex_question_extraction_enabled: bool = Field(
        default=False, alias="CODEX_QUESTION_EXTRACTION_ENABLED"
    )
    codex_extraction_enabled: bool = Field(default=False, alias="CODEX_EXTRACTION_ENABLED")
    codex_extraction_provider: str = Field(
        default="disabled", alias="CODEX_EXTRACTION_PROVIDER"
    )
    codex_extraction_bridge_command: str = Field(
        default="", alias="CODEX_EXTRACTION_BRIDGE_COMMAND"
    )
    codex_extraction_host_storage_root: str = Field(
        default="/home/newton/teacher-assistant/data",
        alias="CODEX_EXTRACTION_HOST_STORAGE_ROOT",
    )
    codex_browser_grading_enabled: bool = Field(
        default=False, alias="CODEX_BROWSER_GRADING_ENABLED"
    )
    answer_region_grading_crop_padding_ratio: float = Field(
        default=0.10, alias="ANSWER_REGION_GRADING_CROP_PADDING_RATIO"
    )
    semi_automated_mode_enabled: bool = Field(
        default=False, alias="SEMI_AUTOMATED_MODE_ENABLED"
    )
    fully_automated_mode_enabled: bool = Field(
        default=False, alias="FULLY_AUTOMATED_MODE_ENABLED"
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
