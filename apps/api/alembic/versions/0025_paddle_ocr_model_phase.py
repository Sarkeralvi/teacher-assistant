"""Allow the isolated PaddleOCR runtime to own the local GPU lease.

Revision ID: 0025_paddle_ocr_model_phase
Revises: 0024_model_lease_page_evidence
"""

from alembic import op

revision = "0025_paddle_ocr_model_phase"
down_revision = "0024_model_lease_page_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_local_model_lease_phase", "local_model_leases", type_="check")
    op.create_check_constraint(
        "ck_local_model_lease_phase",
        "local_model_leases",
        "model_phase is null or model_phase in ('PaddleOcr', 'Qwen', 'Qwen38')",
    )


def downgrade() -> None:
    # A downgrade is intentionally blocked while Paddle owns the slot instead
    # of deleting or rewriting a live lease behind an inference process.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM local_model_leases WHERE model_phase = 'PaddleOcr'
          ) THEN
            RAISE EXCEPTION 'Release the PaddleOcr model lease before downgrading';
          END IF;
        END $$;
        """
    )
    op.drop_constraint("ck_local_model_lease_phase", "local_model_leases", type_="check")
    op.create_check_constraint(
        "ck_local_model_lease_phase",
        "local_model_leases",
        "model_phase is null or model_phase in ('Qwen', 'Qwen38')",
    )
