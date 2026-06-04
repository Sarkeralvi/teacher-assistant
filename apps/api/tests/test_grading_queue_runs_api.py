# ruff: noqa: F401,F811

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import (
    AnswerRegion,
    AnswerRegionSegment,
    BatchEvidencePrepRun,
    FinalGrade,
    GradeSuggestion,
    GradingJob,
    GradingQueueItem,
    GradingQueueRun,
    GradingRun,
    SubmissionPage,
)
from tests.test_evidence_prep_runs_api import (
    client,
    create_assessment_fixture,
    create_question_with_optional_rubric,
    create_region_for_packet,
    db_session,
    register_teacher,
    upload_submission,
)


def test_queue_run_includes_only_confirmed_ready_packets_and_refuses_everything_else(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    teacher, token = register_teacher(client, "queue-mixed")
    course = client.post(
        "/courses",
        json={"teacher_id": teacher["id"], "code": "QUEUE101", "title": "Queue"},
    ).json()
    assessment = client.post(
        f"/courses/{course['id']}/assessments",
        json={"title": "Queue Midterm", "assessment_type": "exam", "total_marks": "15.00"},
    ).json()
    q1 = create_question_with_optional_rubric(client, assessment["id"], "1", active_rubric=True)
    q2 = create_question_with_optional_rubric(client, assessment["id"], "2", active_rubric=True)
    q3 = create_question_with_optional_rubric(client, assessment["id"], "3", active_rubric=False)
    s1 = upload_submission(client, tmp_path, assessment["id"], "S-001")
    s2 = upload_submission(client, tmp_path, assessment["id"], "S-002")

    ready_region = create_region_for_packet(client, s1, q1)
    ready_response = client.patch(
        f"/answer-regions/{ready_region['id']}/corrections/full-answer-confirmation",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "full_answer_confirmed": True,
            "continuation_not_needed": True,
            "packet_status": "complete",
        },
    )
    assert ready_response.status_code == 200

    unconfirmed_region = create_region_for_packet(client, s1, q3)
    partial_region = create_region_for_packet(client, s2, q1)
    blank_region = create_region_for_packet(client, s2, q2)
    continuation_region = create_region_for_packet(client, s2, q3)
    for region_id, packet_status in (
        (unconfirmed_region["id"], "unconfirmed"),
        (partial_region["id"], "partial"),
        (blank_region["id"], "blank"),
        (continuation_region["id"], "complete"),
    ):
        region = db_session.get(AnswerRegion, region_id)
        assert region is not None
        region.evidence_status = packet_status
        region.full_answer_confirmed = packet_status == "complete"
        if packet_status in {"partial", "blank"}:
            region.continuation_check_status = "continuation_confirmed_not_needed"
    continuation = db_session.get(AnswerRegion, continuation_region["id"])
    assert continuation is not None
    continuation.full_answer_confirmed = False
    continuation.y = 82
    continuation.height = 15
    s2_pages = s2["pages"]
    assert isinstance(s2_pages, list)
    db_session.add(
        SubmissionPage(
            submission_id=continuation.submission_id,
            page_no=2,
            image_path=s2_pages[0]["image_path"],
        )
    )
    db_session.commit()

    prep_response = client.post(
        f"/assessments/{assessment['id']}/evidence-prep-runs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert prep_response.status_code == 201
    prep_run = prep_response.json()

    response = client.post(
        f"/assessments/{assessment['id']}/grading-queue-runs",
        headers={"Authorization": f"Bearer {token}"},
        json={"evidence_prep_run_id": prep_run["id"]},
    )

    assert response.status_code == 201
    run = response.json()
    assert run["assessment_id"] == assessment["id"]
    assert run["evidence_prep_run_id"] == prep_run["id"]
    assert run["created_by_teacher_id"] == teacher["id"]
    assert run["status"] == "built"
    assert run["total_candidate_packets"] == 6
    assert run["queued_item_count"] == 1
    assert run["refused_item_count"] == 5
    assert len(run["items"]) == 1
    assert len(run["refused_items"]) == 5

    item = run["items"][0]
    assert item["queue_status"] == "pending_review"
    assert item["provider_allowed"] is False
    assert item["assessment_id"] == assessment["id"]
    assert item["submission_id"] == s1["id"]
    assert item["student_identifier"] == "S-001"
    assert item["question_id"] == q1["id"]
    assert item["grading_unit_id"] == q1["id"]
    assert item["grading_unit_label"] == "1"
    assert item["max_marks"] == "5.00"
    assert item["answer_region_id"] == ready_region["id"]
    assert item["segment_count"] == 1
    assert item["pages_covered"] == [1]
    assert item["evidence_status"] == "complete"
    assert item["continuation_check_status"] == "continuation_confirmed_not_needed"
    assert item["readiness_snapshot_json"]["ready_for_grading"] is True
    assert item["readiness_snapshot_json"]["blockers"] == []

    refused = {
        (packet["student_identifier"], packet["grading_unit_label"]): packet
        for packet in run["refused_items"]
    }
    assert "no answer region mapped for this submission/question" in refused[("S-001", "2")][
        "refusal_reasons"
    ]
    assert "evidence packet is not confirmed complete" in refused[("S-001", "3")][
        "refusal_reasons"
    ]
    assert "missing active rubric" in refused[("S-001", "3")]["refusal_reasons"]
    assert "partial evidence packet requires teacher review" in refused[("S-002", "1")][
        "refusal_reasons"
    ]
    assert "confirmed blank packet is not enabled for grading" in refused[("S-002", "2")][
        "refusal_reasons"
    ]
    assert "possible answer continuation not confirmed" in refused[("S-002", "3")][
        "refusal_reasons"
    ]

    assert db_session.query(GradingQueueRun).count() == 1
    assert db_session.query(GradingQueueItem).count() == 1
    assert db_session.query(GradeSuggestion).count() == 0
    assert db_session.query(FinalGrade).count() == 0
    assert db_session.query(GradingJob).count() == 0
    assert db_session.query(GradingRun).count() == 0


def test_queue_run_requires_owner_teacher(client: TestClient, tmp_path: Path) -> None:
    data = create_assessment_fixture(client, tmp_path)
    owner_response = client.post(
        f"/assessments/{data['assessment']['id']}/grading-queue-runs",
        headers={"Authorization": f"Bearer {data['token']}"},
    )
    assert owner_response.status_code == 201
    _, other_token = register_teacher(client, "other-queue")

    create_response = client.post(
        f"/assessments/{data['assessment']['id']}/grading-queue-runs",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    read_response = client.get(
        f"/assessments/{data['assessment']['id']}/grading-queue-runs/{owner_response.json()['id']}",
        headers={"Authorization": f"Bearer {other_token}"},
    )

    assert create_response.status_code == 404
    assert read_response.status_code == 404


def test_queue_summary_reports_latest_scaffold_without_creating_grades(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = create_assessment_fixture(client, tmp_path)
    create_response = client.post(
        f"/assessments/{data['assessment']['id']}/grading-queue-runs",
        headers={"Authorization": f"Bearer {data['token']}"},
    )
    assert create_response.status_code == 201

    summary_response = client.get(
        f"/assessments/{data['assessment']['id']}/grading-queue-summary",
        headers={"Authorization": f"Bearer {data['token']}"},
    )

    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["queued_item_count"] == 1
    assert summary["refused_item_count"] == 0
    assert summary["items"][0]["provider_allowed"] is False
    assert db_session.query(GradeSuggestion).count() == 0
    assert db_session.query(FinalGrade).count() == 0
    assert db_session.query(GradingJob).count() == 0


def test_queue_test_cleanup_models_are_present() -> None:
    # Keeps the import of delete live and documents cleanup order expectations for future tests.
    assert delete is not None
    assert BatchEvidencePrepRun.__tablename__ == "batch_evidence_prep_runs"


def test_staleness_validation_marks_segment_edits_and_blocked_evidence(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = create_assessment_fixture(client, tmp_path)
    response = client.post(
        f"/assessments/{data['assessment']['id']}/grading-queue-runs",
        headers={"Authorization": f"Bearer {data['token']}"},
    )
    assert response.status_code == 201
    run = response.json()
    assert run["items"][0]["stale_status"] == "fresh"

    fresh_response = client.post(
        f"/assessments/{data['assessment']['id']}/grading-queue-runs/{run['id']}/validate-staleness",
        headers={"Authorization": f"Bearer {data['token']}"},
    )
    assert fresh_response.status_code == 200
    fresh_run = fresh_response.json()
    assert fresh_run["items"][0]["stale_status"] == "fresh"

    segment = db_session.query(AnswerRegionSegment).filter_by(
        answer_region_id=run["items"][0]["answer_region_id"]
    ).one()
    segment.x = 9
    db_session.commit()

    stale_response = client.post(
        f"/assessments/{data['assessment']['id']}/grading-queue-runs/{run['id']}/validate-staleness",
        headers={"Authorization": f"Bearer {data['token']}"},
    )
    assert stale_response.status_code == 200
    stale_run = stale_response.json()
    assert stale_run["items"][0]["stale_status"] == "stale"
    assert stale_run["items"][0]["provider_allowed"] is False

    region = db_session.get(AnswerRegion, run["items"][0]["answer_region_id"])
    assert region is not None
    region.evidence_status = "partial"
    region.full_answer_confirmed = False
    db_session.commit()

    blocked_response = client.post(
        f"/assessments/{data['assessment']['id']}/grading-queue-runs/{run['id']}/validate-staleness",
        headers={"Authorization": f"Bearer {data['token']}"},
    )
    assert blocked_response.status_code == 200
    blocked_run = blocked_response.json()
    assert blocked_run["items"][0]["stale_status"] == "blocked_now"
    assert "partial evidence packet requires teacher review" in blocked_run["items"][0][
        "current_refusal_reasons"
    ]
    assert db_session.query(GradeSuggestion).count() == 0
    assert db_session.query(FinalGrade).count() == 0
    assert db_session.query(GradingJob).count() == 0


def test_rebuild_keeps_old_run_auditable_and_recomputes_current_refusals(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    data = create_assessment_fixture(client, tmp_path)
    first_response = client.post(
        f"/assessments/{data['assessment']['id']}/grading-queue-runs",
        headers={"Authorization": f"Bearer {data['token']}"},
    )
    assert first_response.status_code == 201
    first_run = first_response.json()
    assert first_run["queued_item_count"] == 1
    assert first_run["refused_item_count"] == 0

    region = db_session.get(AnswerRegion, first_run["items"][0]["answer_region_id"])
    assert region is not None
    region.evidence_status = "blank"
    region.full_answer_confirmed = True
    region.continuation_check_status = "continuation_confirmed_not_needed"
    db_session.commit()

    second_response = client.post(
        f"/assessments/{data['assessment']['id']}/grading-queue-runs",
        headers={"Authorization": f"Bearer {data['token']}"},
    )
    assert second_response.status_code == 201
    second_run = second_response.json()
    assert second_run["id"] != first_run["id"]
    assert second_run["queued_item_count"] == 0
    assert second_run["refused_item_count"] == 1
    assert "confirmed blank packet is not enabled for grading" in second_run["refused_items"][0][
        "refusal_reasons"
    ]
    assert second_run["refused_items"][0]["blockers"]
    assert second_run["refused_items"][0]["snapshot_hash"]

    old_response = client.get(
        f"/assessments/{data['assessment']['id']}/grading-queue-runs/{first_run['id']}",
        headers={"Authorization": f"Bearer {data['token']}"},
    )
    assert old_response.status_code == 200
    old_run = old_response.json()
    assert old_run["queued_item_count"] == 1
    assert old_run["items"][0]["stale_status"] == "blocked_now"
    assert db_session.query(GradingQueueRun).count() == 2
    assert db_session.query(GradingQueueItem).count() == 1
    assert db_session.query(GradeSuggestion).count() == 0
    assert db_session.query(FinalGrade).count() == 0
    assert db_session.query(GradingJob).count() == 0
