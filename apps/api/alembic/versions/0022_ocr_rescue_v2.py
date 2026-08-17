"""Allow explicitly labeled cross-engine OCR candidates.

Revision ID: 0022_ocr_rescue_v2
Revises: 0021_answer_region_ocr_rescue
Create Date: 2026-08-17
"""

import sqlalchemy as sa

from alembic import op

revision = "0022_ocr_rescue_v2"
down_revision = "0021_answer_region_ocr_rescue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ux_answer_region_ocr_rescue_active", table_name="answer_region_ocr_runs")
    op.create_index(
        "ux_answer_region_ocr_rescue_active",
        "answer_region_ocr_runs",
        ["answer_region_id"],
        unique=True,
        postgresql_where=sa.text(
            "profile like 'math_handwriting_rescue%' "
            "and status in ('queued', 'running')"
        ),
    )
    op.drop_constraint(
        "ck_ocr_candidate_engine", "answer_region_ocr_candidates", type_="check"
    )
    op.create_check_constraint(
        "ck_ocr_candidate_engine",
        "answer_region_ocr_candidates",
        "engine in ('ppocr_v6', 'paddleocr_vl', 'paddle_ensemble')",
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM answer_region_ocr_candidates WHERE engine = 'paddle_ensemble'"
    )
    op.drop_constraint(
        "ck_ocr_candidate_engine", "answer_region_ocr_candidates", type_="check"
    )
    op.create_check_constraint(
        "ck_ocr_candidate_engine",
        "answer_region_ocr_candidates",
        "engine in ('ppocr_v6', 'paddleocr_vl')",
    )
    op.drop_index("ux_answer_region_ocr_rescue_active", table_name="answer_region_ocr_runs")
    op.create_index(
        "ux_answer_region_ocr_rescue_active",
        "answer_region_ocr_runs",
        ["answer_region_id"],
        unique=True,
        postgresql_where=sa.text(
            "profile = 'math_handwriting_rescue' and status in ('queued', 'running')"
        ),
    )
