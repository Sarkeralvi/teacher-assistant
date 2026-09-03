from __future__ import annotations

from pathlib import Path

import pytest


def _find_repo_root() -> Path | None:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "apps" / "web" / "lib" / "api.ts").exists():
            return candidate
    return None


_repo_root = _find_repo_root()
if _repo_root is None:
    pytest.skip(
        "frontend sources not available (containerized backend-only run)",
        allow_module_level=True,
    )

REPO_ROOT = _repo_root
WEB_API = REPO_ROOT / "apps" / "web" / "lib" / "api.ts"
ASSESSMENT_DETAIL = REPO_ROOT / "apps" / "web" / "components" / "AssessmentDetailClient.tsx"
ASSESSMENT_REVIEW = REPO_ROOT / "apps" / "web" / "components" / "AssessmentReviewClient.tsx"
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
    api_request_end = source.index("export type AuthRegister")
    api_request = source[api_request_start:api_request_end]
    assert "catch" in api_request


def test_protected_page_and_export_downloads_use_bearer_authenticated_fetches() -> None:
    api_source = _read(WEB_API)
    assessment_source = _read(ASSESSMENT_DETAIL)
    review_source = _read(ASSESSMENT_REVIEW)

    assert "export function downloadSubmissionPageImage" in api_source
    assert 'apiDownload(`/submission-pages/${pageId}/image`)' in api_source
    assert "export function downloadAssessmentFinalGrades" in api_source
    assert 'apiDownload(`/assessments/${assessmentId}/export/final-grades.xlsx`)' in api_source
    assert "Authorization" in api_source[api_source.index("async function apiDownload") :]
    assert "href={getSubmissionPageImageUrl" not in assessment_source
    assert "downloadSubmissionPageImage" in assessment_source
    assert "getAssessmentFinalGradesExportUrl" not in review_source
    assert "downloadAssessmentFinalGrades" in review_source


def test_controlled_grading_upload_refreshes_material_state_after_success() -> None:
    source = _read(CONTROLLED_WIZARD)
    upload_start = source.index("async function handleUpload(")
    upload_end = source.index("async function handleStartExtraction")
    upload_handler = source[upload_start:upload_end]

    assert "setRun(updated)" in upload_handler
    assert "getReferenceExtraction(updated.id)" in upload_handler


def test_cloud_transfer_confirmation_is_carried_from_teacher_actions() -> None:
    api_source = _read(WEB_API)
    reference_start = api_source.index("export function startReferenceExtraction")
    reference_end = api_source.index("export function listAnswerRegionTranscriptionRuns")
    reference_helper = api_source[reference_start:reference_end]
    assert "provider_data_boundary_confirmed: providerDataBoundaryConfirmed" in reference_helper
    assert 'brain.location === "cloud"' not in reference_helper

    bulk_start = api_source.index("export function createBulkEvaluationRun")
    bulk_end = api_source.index("export function getBulkEvaluationRun")
    bulk_helper = api_source[bulk_start:bulk_end]
    assert "String(payload.provider_data_boundary_confirmed)" in bulk_helper
    assert 'String(payload.location === "cloud")' not in bulk_helper

    controlled_source = _read(CONTROLLED_WIZARD)
    assert "startReferenceExtraction(" in controlled_source
    assert "materialsConfirmed," in controlled_source

    bulk_workspace = _read(REPO_ROOT / "apps" / "web" / "components" / "BulkEvaluationClient.tsx")
    assert "provider_data_boundary_confirmed: authorized" in bulk_workspace


def test_assessment_workflow_has_stable_browser_target_markers() -> None:
    source = _read(REPO_ROOT / "apps" / "web" / "components" / "AssessmentDetailClient.tsx")
    assert 'data-testid="answer-region-page-select"' in source
    assert 'data-testid="answer-region-question-select"' in source
    assert 'data-testid="answer-region-card"' in source
    assert 'data-testid="submission-file-input"' in source
    assert 'data-testid="zip-file-input"' in source


def test_review_queue_has_stable_browser_target_markers() -> None:
    source = _read(REPO_ROOT / "apps" / "web" / "components" / "AssessmentReviewClient.tsx")
    assert 'data-testid="review-queue-filter"' in source
    assert 'data-testid="review-card"' in source
    assert 'data-testid="select-all-visible-suggested-items-button"' in source
    assert 'data-testid="approve-selected-button"' in source


def test_teacher_review_ui_excludes_obsolete_mock_and_codex_actions() -> None:
    review_source = _read(
        REPO_ROOT / "apps" / "web" / "components" / "AssessmentReviewClient.tsx"
    )
    assessment_source = _read(
        REPO_ROOT / "apps" / "web" / "components" / "AssessmentDetailClient.tsx"
    )

    assert "batchMockGradeAssessment" not in review_source
    assert "gradeAnswerRegionWithCodexDev" not in review_source
    assert "Brain-suggested score" in review_source
    assert "gradeAnswerRegionWithBrain" in assessment_source
    assert "Grade confirmed answer with the configured brain" in assessment_source


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
