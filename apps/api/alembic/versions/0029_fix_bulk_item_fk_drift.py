"""Fix bulk_evaluation_items optional FKs: they were created as NO ACTION
instead of the ON DELETE SET NULL the model has always declared.

Discovered when a submission delete failed with a ForeignKeyViolation on
transcription_run_id: the answer_region -> answer_region_ocr_run cascade
deleted an OCR run that a bulk_evaluation_items row still pointed to, and
NO ACTION (the live constraint) rejected that instead of nulling the
reference the way SET NULL (the constraint the model and migration 0026
both specify) would have.

Six FKs on this table have the same drift: mapping_id, answer_region_id,
transcription_run_id, grading_job_id, grade_suggestion_id, final_grade_id.
This migration recreates each with the correct ON DELETE SET NULL, which
matches app/models.py exactly. No data is changed.

Revision ID: 0029_fix_bulk_item_fk_drift
Revises: 0028_visual_page_read
"""

from alembic import op

revision = "0029_fix_bulk_item_fk_drift"
down_revision = "0028_visual_page_read"
branch_labels = None
depends_on = None

_DRIFTED_FKS = (
    ("bulk_evaluation_items_mapping_id_fkey", "mapping_id", "answer_region_mappings"),
    ("bulk_evaluation_items_answer_region_id_fkey", "answer_region_id", "answer_regions"),
    (
        "bulk_evaluation_items_transcription_run_id_fkey",
        "transcription_run_id",
        "answer_region_ocr_runs",
    ),
    ("bulk_evaluation_items_grading_job_id_fkey", "grading_job_id", "grading_jobs"),
    (
        "bulk_evaluation_items_grade_suggestion_id_fkey",
        "grade_suggestion_id",
        "grade_suggestions",
    ),
    ("bulk_evaluation_items_final_grade_id_fkey", "final_grade_id", "final_grades"),
)


def upgrade() -> None:
    for constraint_name, column_name, target_table in _DRIFTED_FKS:
        op.drop_constraint(constraint_name, "bulk_evaluation_items", type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            "bulk_evaluation_items",
            target_table,
            [column_name],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for constraint_name, column_name, target_table in _DRIFTED_FKS:
        op.drop_constraint(constraint_name, "bulk_evaluation_items", type_="foreignkey")
        op.create_foreign_key(
            constraint_name,
            "bulk_evaluation_items",
            target_table,
            [column_name],
            ["id"],
        )
