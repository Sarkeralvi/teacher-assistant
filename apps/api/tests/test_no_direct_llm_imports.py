from pathlib import Path

FORBIDDEN_IMPORTS = (
    "import openai",
    "from openai",
    "import anthropic",
    "from anthropic",
    "google.generativeai",
)


def test_no_direct_llm_provider_imports_outside_brain_adapter() -> None:
    app_root = Path(__file__).resolve().parents[1] / "app"
    violations: list[str] = []

    for path in app_root.rglob("*.py"):
        relative = path.relative_to(app_root)
        if relative.parts[:2] == ("modules", "brain_adapter"):
            continue
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_IMPORTS:
            if forbidden in text:
                violations.append(f"{relative}: {forbidden}")

    assert violations == []
