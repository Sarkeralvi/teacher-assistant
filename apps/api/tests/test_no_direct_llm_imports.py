from pathlib import Path

FORBIDDEN_IMPORTS = (
    "import openai",
    "from openai",
    "import anthropic",
    "from anthropic",
    "google.generativeai",
    "from google import genai",
    "from google.genai",
    "import google.genai",
)


def test_no_direct_llm_provider_imports_outside_brain_adapter() -> None:
    api_root = Path(__file__).resolve().parents[1]
    violations: list[str] = []

    for path in api_root.rglob("*.py"):
        relative = path.relative_to(api_root)
        if relative.parts[:2] == ("packages", "brain"):
            continue
        if path == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_IMPORTS:
            if forbidden in text:
                violations.append(f"{relative}: {forbidden}")

    assert violations == []
