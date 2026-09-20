"""Record why each block is attached to its question.

Ownership previously ran twice: ``assemble`` walked the page blocks and
``derive_assignments`` walked the stored blocks, each deciding for itself which
question an unlabelled block belonged to. Two rules for one fact can disagree,
and the visible symptom would be a crop showing evidence the assignment layer
considers unplaced. They now share one rule, and this column records which
branch of it attached a block:

* ``explicit_label``        - the read reported a heading matching a canonical
                              question. A teacher can check this against the page.
* ``same_page_reading_order`` - an unlabelled block directly below its owner on
                              the same page. Reading order here is observed.
* ``declared_continuation`` - an unlabelled block on a later page that the read
                              explicitly marked as continuing. Across a page
                              break nothing is inherited without that claim; a
                              block that does not make it stays unplaced and
                              visible instead of being handed to whichever
                              question happened to come last.

Backfilled to ``explicit_label`` because the previous rule only ever attached a
block that was either labelled or inherited on the same page; no existing row
can have crossed a page break without a continuation claim.

Revision ID: 0033_evidence_basis
Revises: 0032_answer_evidence
"""

import sqlalchemy as sa

from alembic import op

revision = "0033_evidence_basis"
down_revision = "0032_answer_evidence"
branch_labels = None
depends_on = None

_BASES = "'explicit_label', 'same_page_reading_order', 'declared_continuation'"


def upgrade() -> None:
    op.add_column(
        "answer_evidence_spans",
        sa.Column("assignment_basis", sa.String(length=32), nullable=True),
    )
    op.execute("update answer_evidence_spans set assignment_basis = 'explicit_label'")
    op.alter_column("answer_evidence_spans", "assignment_basis", nullable=False)
    op.create_check_constraint(
        "ck_answer_evidence_span_basis",
        "answer_evidence_spans",
        f"assignment_basis in ({_BASES})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_answer_evidence_span_basis", "answer_evidence_spans", type_="check"
    )
    op.drop_column("answer_evidence_spans", "assignment_basis")
