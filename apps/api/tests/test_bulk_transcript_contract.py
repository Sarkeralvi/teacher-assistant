"""Bulk authorization must never silently select a mapping-first pipeline."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.services import bulk_evaluation_service as bulk


def test_mapping_only_profile_is_rejected_before_dispatch(monkeypatch):
    policy = SimpleNamespace(page_read_enabled=False)
    monkeypatch.setattr(bulk, "brain_policy_for_profile", lambda *_: policy)
    lease = MagicMock()
    monkeypatch.setattr(bulk, "hold_brain_execution", lease)
    service = bulk.BulkEvaluationService(
        MagicMock(), settings=Settings(_env_file=None), storage=MagicMock(),
    )
    with pytest.raises(bulk.BulkEvaluationError, match="whole-page transcription"):
        service._assert_enabled("test-model", 10, provider="mapping-only")
    lease.assert_not_called()


def test_bulk_page_read_receives_selected_adapter(monkeypatch):
    db = MagicMock()
    submission = SimpleNamespace(id=11, pages=[object()])
    item = SimpleNamespace(status="pending")
    db.scalar.return_value = submission
    db.get.return_value = SimpleNamespace(id=1)
    db.scalars.return_value.all.return_value = [item]
    service = bulk.BulkEvaluationService(
        db, settings=Settings(_env_file=None), storage=MagicMock(),
    )
    service._next_read_submission = lambda _: 11
    service._existing_submission_mappings = lambda _: []
    adapter = object()
    service._policy_for_run = lambda _: SimpleNamespace(adapter=adapter)

    def factory(*args, **kwargs):
        assert kwargs["qwen_adapter"] is adapter
        raise RuntimeError("verified selected adapter before dispatch")

    monkeypatch.setattr(bulk, "LocalScriptPageReadService", factory)
    run = SimpleNamespace(
        id=1, created_by_teacher_id=1, authorized_call_limit=10, calls_used=0,
        import_manifest={"visual_evidence_path": "page_read"},
    )
    with pytest.raises(RuntimeError, match="verified selected adapter"):
        service._process_read(run)
