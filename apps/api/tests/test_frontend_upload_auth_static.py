from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_API = REPO_ROOT / "apps" / "web" / "lib" / "api.ts"
CONTROLLED_WIZARD = (
    REPO_ROOT / "apps" / "web" / "components" / "CustomControlledGradingRunClient.tsx"
)
WEB_ROOT = REPO_ROOT / "apps" / "web"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_controlled_grading_material_upload_uses_auth_token_and_formdata_safely() -> None:
    source = _read(WEB_API)
    upload_start = source.index("export function uploadGradingRunMaterials")
    upload_end = source.index("export function acceptQuestionImportDrafts")
    upload_section = source[upload_start:upload_end]

    assert "new FormData()" in upload_section
    assert "formData.append(\"question_pdf\"" in upload_section
    assert "formData.append(\"solution_pdf\"" in upload_section
    assert "formData.append(\"rubric_pdf\"" in upload_section
    assert "token: getStoredAuthToken()" in upload_section
    assert "Content-Type" not in upload_section


def test_all_frontend_formdata_uploads_do_not_set_multipart_content_type() -> None:
    source = _read(WEB_API)
    for function_name in [
        "importQuestionsFromPaper",
        "uploadGradingRunMaterials",
        "uploadSubmission",
    ]:
        start = source.index(f"export function {function_name}")
        next_export = source.find("\nexport function ", start + 1)
        section = source[start : next_export if next_export != -1 else len(source)]
        assert "formData" in section
        assert "Content-Type" not in section
        assert "multipart/form-data" not in section


def test_api_request_has_clear_auth_and_backend_unreachable_messages() -> None:
    source = _read(WEB_API)

    assert "Please log in again before uploading materials." in source
    assert "Could not reach backend at" in source
    assert "Check backend server." in source
    assert "response.status === 401" in source
    api_request_start = source.index("async function apiRequest")
    api_request_end = source.index("export type UserCreate")
    api_request = source[api_request_start:api_request_end]
    assert "catch" in api_request


def test_controlled_grading_upload_refreshes_material_state_after_success() -> None:
    source = _read(CONTROLLED_WIZARD)
    upload_start = source.index("async function handleUploadMaterials")
    upload_end = source.index("async function handleUpdateRun")
    upload_handler = source[upload_start:upload_end]

    assert "await load();" in upload_handler


def test_frontend_has_no_direct_codex_or_llm_calls() -> None:
    forbidden = ["openai", "anthropic", "gemini", "claude", "codex exec", "api.openai.com"]
    checked_suffixes = {".ts", ".tsx"}
    offenders: list[str] = []
    for path in WEB_ROOT.rglob("*"):
        is_ignored_dir = ".next" in path.parts or "node_modules" in path.parts
        if is_ignored_dir or path.suffix not in checked_suffixes:
            continue
        lower = path.read_text(encoding="utf-8").lower()
        if any(term in lower for term in forbidden):
            offenders.append(str(path.relative_to(WEB_ROOT)))

    assert offenders == []
