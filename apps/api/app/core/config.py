from decimal import Decimal
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
    local_qwen_enabled: bool = Field(default=False, alias="LOCAL_QWEN_ENABLED")
    local_qwen_base_url: str = Field(
        # Not 8080: a separate Qwen3.6 coding-assistant bridge commonly holds
        # that port, and sharing it makes both contend for one single-slot server.
        default="http://127.0.0.1:8086/v1",
        alias="LOCAL_QWEN_BASE_URL",
    )
    local_qwen_model: str = Field(default="qwen3.6-35b-a3b-q4km", alias="LOCAL_QWEN_MODEL")
    local_qwen_api_key: str = Field(default="", alias="LOCAL_QWEN_API_KEY")
    local_qwen_timeout_seconds: float = Field(
        default=600.0, alias="LOCAL_QWEN_TIMEOUT_SECONDS", gt=0
    )

    local_reference_extraction_enabled: bool = Field(
        default=False, alias="LOCAL_REFERENCE_EXTRACTION_ENABLED"
    )
    local_script_preparation_enabled: bool = Field(
        default=False, alias="LOCAL_SCRIPT_PREPARATION_ENABLED"
    )
    local_single_answer_grading_enabled: bool = Field(
        default=False, alias="LOCAL_SINGLE_ANSWER_GRADING_ENABLED"
    )
    local_ai_phase_switch_enabled: bool = Field(
        default=False, alias="LOCAL_AI_PHASE_SWITCH_ENABLED"
    )
    local_ai_phase_timeout_seconds: int = Field(
        default=600, alias="LOCAL_AI_PHASE_TIMEOUT_SECONDS", ge=30, le=1800
    )

    local_reference_job_timeout_seconds: int = Field(
        default=2400, alias="LOCAL_REFERENCE_JOB_TIMEOUT_SECONDS", ge=300, le=3600
    )

    # Tier-1 OCR. Disabled by default: enabling it changes which model reads a
    # teacher's reference material, so it is an explicit operator decision.
    local_ocr_enabled: bool = Field(default=False, alias="LOCAL_OCR_ENABLED")
    local_ocr_render_dpi: int = Field(
        default=300, alias="LOCAL_OCR_RENDER_DPI", ge=72, le=600
    )
    # Escalations are a pre-authorized budget, not a silent fallback. Exhausting
    # it is a hard failure so a run cannot quietly degrade into reading nothing.
    local_reference_max_escalations: int = Field(
        default=6, alias="LOCAL_REFERENCE_MAX_ESCALATIONS", ge=0, le=25
    )
    # Calibrated 2026-08-20 against 10 teacher-verified fixtures. Set below the
    # 0.79 minimum observed on a perfectly-read printed page, so a good printed
    # page is not escalated over one merely-lower-scoring line. Confidence is a
    # weak signal on harder material; handwriting escalates by document role and
    # fragmented math by geometry, not by this number.
    local_ocr_confidence_escalate_below: Decimal = Field(
        default=Decimal("0.70"),
        alias="LOCAL_OCR_CONFIDENCE_ESCALATE_BELOW",
        ge=Decimal("0"),
        le=Decimal("1"),
    )
    local_ocr_uncovered_ink_escalate_above: Decimal = Field(
        default=Decimal("0.20"),
        alias="LOCAL_OCR_UNCOVERED_INK_ESCALATE_ABOVE",
        ge=Decimal("0"),
        le=Decimal("1"),
    )
    # Rubric format varies by teacher and course: some are typed, some are
    # handwritten mark sheets. A handwritten one must escalate wholesale, but
    # forcing that on a typed rubric would spend the vision model for nothing.
    # Defaults true because it fails safe - a needless escalation costs time,
    # a trusted misreading costs a mark.
    local_ocr_treat_rubric_as_handwritten: bool = Field(
        default=True, alias="LOCAL_OCR_TREAT_RUBRIC_AS_HANDWRITTEN"
    )
    cohort_model_grading_enabled: bool = Field(default=False, alias="COHORT_MODEL_GRADING_ENABLED")
    cohort_max_provider_calls: int = Field(
        default=25, alias="COHORT_MAX_PROVIDER_CALLS", ge=1, le=25
    )
    cohort_provider_retry_count: int = Field(
        default=0, alias="COHORT_PROVIDER_RETRY_COUNT", ge=0, le=0
    )
    cohort_dispatch_heartbeat_timeout_seconds: int = Field(
        default=600, alias="COHORT_DISPATCH_HEARTBEAT_TIMEOUT_SECONDS", ge=30
    )
    answer_region_suggestion_provider: str = Field(
        default="mock", alias="ANSWER_REGION_SUGGESTION_PROVIDER"
    )
    codex_answer_region_suggestions_enabled: bool = Field(
        default=False, alias="CODEX_ANSWER_REGION_SUGGESTIONS_ENABLED"
    )
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_MODEL")
    gemini_image_input_enabled: bool = Field(default=False, alias="GEMINI_IMAGE_INPUT_ENABLED")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="", alias="OPENAI_MODEL")
    openai_base_url: str = Field(default="", alias="OPENAI_BASE_URL")
    openai_image_input_enabled: bool = Field(default=False, alias="OPENAI_IMAGE_INPUT_ENABLED")
    openai_timeout_seconds: float = Field(default=30.0, alias="OPENAI_TIMEOUT_SECONDS")
    jwt_secret_key: str = Field(default="dev-only-change-me", alias="JWT_SECRET_KEY")
    jwt_expire_minutes: int = Field(default=480, alias="JWT_EXPIRE_MINUTES")
    cors_allowed_origins: str = Field(
        default="http://localhost:3000,http://host.docker.internal:3000",
        alias="CORS_ALLOWED_ORIGINS",
    )
    codex_cli_command: str = Field(default="codex", alias="CODEX_CLI_COMMAND")
    codex_cli_model: str = Field(default="gpt-5.5", alias="CODEX_CLI_MODEL")
    codex_cli_timeout_seconds: float = Field(default=300.0, alias="CODEX_CLI_TIMEOUT_SECONDS")
    codex_cli_sandbox: str = Field(default="read-only", alias="CODEX_CLI_SANDBOX")
    codex_cli_approval_policy: str = Field(default="never", alias="CODEX_CLI_APPROVAL_POLICY")
    codex_cli_use_json: bool = Field(default=True, alias="CODEX_CLI_USE_JSON")
    codex_cli_output_last_message: bool = Field(default=True, alias="CODEX_CLI_OUTPUT_LAST_MESSAGE")
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
    codex_extraction_provider: str = Field(default="disabled", alias="CODEX_EXTRACTION_PROVIDER")
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
    semi_automated_mode_enabled: bool = Field(default=False, alias="SEMI_AUTOMATED_MODE_ENABLED")
    fully_automated_mode_enabled: bool = Field(default=False, alias="FULLY_AUTOMATED_MODE_ENABLED")
    # Qwen3.8-27B vision provider (disabled by default; protected by brain_allow_real_providers)
    local_qwen38_enabled: bool = Field(default=False, alias="LOCAL_QWEN38_ENABLED")
    local_qwen38_base_url: str = Field(
        default="http://127.0.0.1:8085/v1", alias="LOCAL_QWEN38_BASE_URL"
    )
    local_qwen38_model: str = Field(default="qwen3.8-27b-q4km", alias="LOCAL_QWEN38_MODEL")
    local_qwen38_api_key: str = Field(default="", alias="LOCAL_QWEN38_API_KEY")
    # 900s was sized from an untested throughput assumption (~8 tok/s); a real
    # run on this hardware measured ~4.35 tok/s sustained decode (CPU/GPU
    # hybrid offload), so 900s undershot a full-ceiling reference-bundle
    # completion by roughly 2x. 1800s covers the 6500-token ceiling with
    # margin at the measured rate.
    local_qwen38_timeout_seconds: float = Field(
        default=1800.0, alias="LOCAL_QWEN38_TIMEOUT_SECONDS", gt=0
    )
    # Must match the running llama-server's -c value (see Start-LocalAi.ps1); used
    # to keep reference-bundle completion budgets from exceeding the server's
    # actual context window instead of guessing at a fixed safe ceiling.
    local_qwen38_context_tokens: int = Field(
        default=12288, alias="LOCAL_QWEN38_CONTEXT_TOKENS", ge=12288, le=32768
    )
    local_qwen38_visual_preparation_enabled: bool = Field(
        default=False, alias="LOCAL_QWEN38_VISUAL_PREPARATION_ENABLED"
    )
    local_qwen38_grading_enabled: bool = Field(default=False, alias="LOCAL_QWEN38_GRADING_ENABLED")
    local_qwen38_grading_reasoning_mode: str = Field(
        default="off", alias="LOCAL_QWEN38_GRADING_REASONING_MODE"
    )
    local_qwen38_model_sha256: str = Field(default="", alias="LOCAL_QWEN38_MODEL_SHA256")
    local_qwen38_mmproj_sha256: str = Field(default="", alias="LOCAL_QWEN38_MMPROJ_SHA256")
    local_qwen38_max_visual_calls: int = Field(
        default=25, alias="LOCAL_QWEN38_MAX_VISUAL_CALLS", ge=1, le=100
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


class InsecureConfigurationError(RuntimeError):
    """Raised when a non-development environment is configured with dev-only defaults."""


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.app_env != "development" and settings.jwt_secret_key == "dev-only-change-me":
        raise InsecureConfigurationError(
            "JWT_SECRET_KEY must be set to a real secret when APP_ENV is not 'development'"
        )
    return settings
