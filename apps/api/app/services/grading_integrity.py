from __future__ import annotations

import hashlib
import json
from typing import Any

from app.models import Question, Rubric


def canonical_json_hash(payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def rubric_snapshot_hash(question: Question, rubric: Rubric) -> str:
    return canonical_json_hash(
        {
            "question_id": question.id,
            "question_text": question.question_text,
            "model_answer": question.model_answer,
            "total_marks": str(question.total_marks),
            "rubric_id": rubric.id,
            "rubric_version": rubric.version,
            "rubric_json": rubric.rubric_json,
            "is_active": rubric.is_active,
        }
    )
