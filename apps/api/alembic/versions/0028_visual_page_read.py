"""Allow the opt-in bulk one-call-per-page evidence-read stage.

Revision ID: 0028_visual_page_read
Revises: 0027_universal_brain
"""

from alembic import op

revision = "0028_visual_page_read"
down_revision = "0027_universal_brain"
branch_labels = None
depends_on = None

_ITEM_STAGES_WITH_PAGE_READ = (
    "stage in ('read', 'mapping', 'transcription', 'grading', 'review', 'complete')"
)
_LEGACY_ITEM_STAGES = "stage in ('mapping', 'transcription', 'grading', 'review', 'complete')"


def upgrade() -> None:
    op.drop_constraint(
        "ck_bulk_evaluation_items_stage",
        "bulk_evaluation_items",
        type_="check",
    )
    op.create_check_constraint(
        "ck_bulk_evaluation_items_stage",
        "bulk_evaluation_items",
        _ITEM_STAGES_WITH_PAGE_READ,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_bulk_evaluation_items_stage",
        "bulk_evaluation_items",
        type_="check",
    )
    op.create_check_constraint(
        "ck_bulk_evaluation_items_stage",
        "bulk_evaluation_items",
        _LEGACY_ITEM_STAGES,
    )
