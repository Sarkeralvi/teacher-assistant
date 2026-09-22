"""The HTTP profile selection must survive the service handoff."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.routes import answer_regions
from app.core.config import Settings
from app.schemas import AnswerRegionMappingRunRequest
from app.services.local_script_preparation import LocalScriptPreparationError
from packages.brain.policy import brain_policy_for_profile


@pytest.mark.parametrize("profile_id", ["codex_cli", "claude_cli", "antigravity_gemini"])
@pytest.mark.parametrize("page_read", [True, False])
def test_mapping_service_uses_the_exact_selected_profile_adapter(
    monkeypatch: pytest.MonkeyPatch, profile_id: str, page_read: bool,
) -> None:
    settings = Settings(
        _env_file=None,
        BRAIN_ALLOW_REAL_PROVIDERS=True,
        BRAIN_MODEL="unrelated-generic-model",
        CODEX_CLI_IMAGE_INPUT_ENABLED=True,
        CLAUDE_CLI_ENABLED=True,
        ANTIGRAVITY_GEMINI_ENABLED=True,
    )
    selected = brain_policy_for_profile(settings, profile_id)
    adapter = selected.adapter
    policy = SimpleNamespace(adapter=adapter, page_read_enabled=page_read)
    monkeypatch.setattr(answer_regions, "get_settings", lambda: settings)
    monkeypatch.setattr(
        answer_regions, "get_submission_or_404",
        lambda *_: SimpleNamespace(id=11, assessment_id=1),
    )
    monkeypatch.setattr(answer_regions, "get_owned_assessment_or_404", lambda *_: None)
    monkeypatch.setattr(
        answer_regions, "_profile_or_legacy_visual_policy",
        lambda *_args, **_kw: (policy, profile_id),
    )

    def service_factory(*_args, **kwargs):
        assert kwargs.get("qwen_adapter") is adapter
        service = MagicMock()
        service.prepare.side_effect = LocalScriptPreparationError("dispatch not needed")
        return service

    monkeypatch.setattr(answer_regions, "LocalScriptPageReadService", service_factory)
    monkeypatch.setattr(answer_regions, "LocalScriptPreparationService", service_factory)
    with pytest.raises(HTTPException, match="dispatch not needed"):
        answer_regions.run_submission_question_node_mappings(
            11,
            AnswerRegionMappingRunRequest(
                provider="brain_visual", profile_id=profile_id,
                expected_model=selected.model, draft_only_confirmed=True,
                provider_data_boundary_confirmed=True,
            ),
            MagicMock(), MagicMock(),
        )
