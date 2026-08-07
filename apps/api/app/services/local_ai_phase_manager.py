from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Literal

from app.core.config import Settings, get_settings

LocalAiPhase = Literal["OcrGpu", "OcrCpu", "Qwen", "Concurrent"]


class LocalAiPhaseError(RuntimeError):
    pass


class LocalAiPhaseManager:
    """Run fixed, repository-owned phase scripts after an explicit teacher action."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        runner: Any | None = None,
        repository_root: Path | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.runner = runner or subprocess.run
        self.repository_root = repository_root or Path(__file__).resolve().parents[4]

    def switch(self, phase: LocalAiPhase) -> None:
        if not self.settings.local_reference_extraction_enabled:
            raise LocalAiPhaseError("Local reference extraction is disabled")
        if not self.settings.local_ai_phase_switch_enabled:
            raise LocalAiPhaseError("Automatic local AI phase switching is disabled")
        if os.name != "nt":
            raise LocalAiPhaseError("Local AI phase switching is supported on Windows host mode")
        script = self.repository_root / "scripts" / "local-ai" / "Switch-LocalAiPhase.ps1"
        if not script.is_file():
            raise LocalAiPhaseError("Local AI phase switch script is unavailable")
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-Phase",
            phase,
            "-HealthTimeoutSeconds",
            str(self.settings.local_ai_phase_timeout_seconds),
        ]
        try:
            result = self.runner(
                command,
                cwd=self.repository_root,
                # The PowerShell script launches a persistent model service.  Do
                # not capture its inherited pipes: on Windows the service can
                # keep those handles open after PowerShell exits, causing
                # subprocess.run() to wait forever for EOF.
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=self.settings.local_ai_phase_timeout_seconds + 30,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LocalAiPhaseError("Local AI phase switch timed out") from exc
        except OSError as exc:
            raise LocalAiPhaseError("Local AI phase switch could not start") from exc
        if result.returncode != 0:
            raise LocalAiPhaseError(
                "Local AI phase switch failed; inspect the local service logs"
            )
