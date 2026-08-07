import os

os.environ.setdefault("BRAIN_PROVIDER", "mock")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://teacher_assistant:teacher_assistant_dev_password@"
    "127.0.0.1:5432/teacher_assistant_test",
)

if (
    os.environ.get("CI", "").lower() != "true"
    and os.environ.get("TA_ALLOW_DESTRUCTIVE_TEST_DATABASE", "").lower() != "true"
    and not os.environ["DATABASE_URL"].rsplit("/", 1)[-1].split("?", 1)[0].endswith("_test")
):
    raise RuntimeError(
        "Refusing destructive API tests outside a *_test database. "
        "Set DATABASE_URL to a disposable test database."
    )
