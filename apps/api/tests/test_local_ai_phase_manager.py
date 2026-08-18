import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services.local_ai_phase_manager import LocalAiPhaseError, LocalAiPhaseManager


def make_script(root: Path) -> None:
    script = root / "scripts" / "local-ai" / "Switch-LocalAiPhase.ps1"
    script.parent.mkdir(parents=True)
    script.write_text("param([string]$Phase)", encoding="utf-8")


def test_phase_manager_uses_only_fixed_repository_script_and_phase(tmp_path: Path) -> None:
    make_script(tmp_path)
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(command: list[str], **kwargs: object):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    settings = Settings(
        LOCAL_REFERENCE_EXTRACTION_ENABLED=True,
        LOCAL_AI_PHASE_SWITCH_ENABLED=True,
        LOCAL_AI_PHASE_TIMEOUT_SECONDS=120,
    )
    manager = LocalAiPhaseManager(
        settings=settings, runner=runner, repository_root=tmp_path
    )

    manager.switch("Qwen")

    command, kwargs = calls[0]
    assert command[:4] == [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
    ]
    assert command[-4:] == ["-Phase", "Qwen", "-HealthTimeoutSeconds", "120"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert "capture_output" not in kwargs


def test_phase_manager_honors_kill_switch_before_starting_process(tmp_path: Path) -> None:
    make_script(tmp_path)
    called = False

    def runner(*_args: object, **_kwargs: object):
        nonlocal called
        called = True
        return SimpleNamespace(returncode=0)

    manager = LocalAiPhaseManager(
        settings=Settings(
            LOCAL_REFERENCE_EXTRACTION_ENABLED=True,
            LOCAL_AI_PHASE_SWITCH_ENABLED=False,
        ),
        runner=runner,
        repository_root=tmp_path,
    )

    with pytest.raises(LocalAiPhaseError, match="disabled"):
        manager.switch("Qwen")
    assert called is False
