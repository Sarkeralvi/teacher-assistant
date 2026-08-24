import re
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint

from app.models import Base

EXPECTED_REVISION_ID = "0024_model_lease_page_evidence"


def _script_directory() -> ScriptDirectory:
    api_root = Path(__file__).resolve().parents[1]
    return ScriptDirectory.from_config(Config(str(api_root / "alembic.ini")))


def _quoted_values(expression: str) -> set[str]:
    return set(re.findall(r"'([^']*)'", expression))


def _metadata_constraint(table_name: str, constraint_name: str) -> str:
    table = Base.metadata.tables[table_name]
    for constraint in table.constraints:
        if isinstance(constraint, CheckConstraint) and constraint.name == constraint_name:
            return str(constraint.sqltext)
    raise AssertionError(f"{table_name} declares no CHECK constraint {constraint_name}")


def test_initial_alembic_migration_exists_and_is_importable() -> None:
    script = _script_directory()

    heads = script.get_heads()

    assert heads == [EXPECTED_REVISION_ID]
    revision = script.get_revision(EXPECTED_REVISION_ID)
    assert revision is not None
    assert revision.module is not None
    assert hasattr(revision.module, "upgrade")
    assert hasattr(revision.module, "downgrade")


@pytest.mark.parametrize(
    ("table_name", "constraint_name", "migration_attribute"),
    [
        (
            "extraction_runs",
            "ck_extraction_runs_provider",
            "_EXTRACTION_PROVIDERS_NEW",
        ),
        (
            "answer_region_ocr_candidates",
            "ck_ocr_candidate_engine",
            "_CANDIDATE_ENGINES_NEW",
        ),
    ],
)
def test_widened_check_constraints_match_the_migration_that_widened_them(
    table_name: str, constraint_name: str, migration_attribute: str
) -> None:
    """The allowed-value list is one fact stored in two places; keep them equal.

    Both of these drifted: 0024 widened the database while ``models.py`` kept the
    narrower list, so a schema built from metadata rejected writes the real
    database accepted. Nothing compared the two, so nothing failed.
    """
    module = _script_directory().get_revision(EXPECTED_REVISION_ID).module
    migration_values = _quoted_values(getattr(module, migration_attribute))
    metadata_values = _quoted_values(_metadata_constraint(table_name, constraint_name))

    assert metadata_values == migration_values
