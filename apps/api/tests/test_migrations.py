from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

EXPECTED_REVISION_ID = "0005_grading_runs"


def test_initial_alembic_migration_exists_and_is_importable() -> None:
    api_root = Path(__file__).resolve().parents[1]
    config = Config(str(api_root / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    heads = script.get_heads()

    assert heads == [EXPECTED_REVISION_ID]
    revision = script.get_revision(EXPECTED_REVISION_ID)
    assert revision is not None
    assert revision.module is not None
    assert hasattr(revision.module, "upgrade")
    assert hasattr(revision.module, "downgrade")
