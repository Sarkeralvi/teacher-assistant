from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Literal

from app.core.config import Settings, get_settings

LocalAiPhase = Literal["Qwen", "Qwen38"]


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
        db: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.runner = runner or subprocess.run
        self.repository_root = repository_root or Path(__file__).resolve().parents[4]
        self.db = db

    def _assert_lease_held(self, lease_holder_id: str) -> None:
        if self.db is None:
            raise LocalAiPhaseError(
                "A model-slot lease was named but no database session was provided "
                "to verify it; refusing to switch the model unverified."
            )
        from app.services.local_model_lease_service import LocalModelLeaseService

        state = LocalModelLeaseService(self.db).read()
        if not state.held or state.holder_id != lease_holder_id:
            raise LocalAiPhaseError(
                "This job does not hold the local model slot, so it must not switch "
                "the model. Another job may be mid-call against the current one."
            )

    def switch(self, phase: LocalAiPhase, *, lease_holder_id: str) -> None:
        """Select a local model phase, unloading the other one.

        ``lease_holder_id`` names the caller's model-slot lease. It is required:
        every application-initiated phase switch must prove that it owns the
        single GPU model slot before it can unload the other model.
        """
        if not (
            self.settings.local_reference_extraction_enabled
            or self.settings.local_script_preparation_enabled
            or self.settings.local_qwen38_visual_preparation_enabled
            or self.settings.local_qwen38_grading_enabled
        ):
            raise LocalAiPhaseError("Local AI features are disabled")
        if not self.settings.local_ai_phase_switch_enabled:
            raise LocalAiPhaseError("Automatic local AI phase switching is disabled")
        if os.name != "nt":
            raise LocalAiPhaseError("Local AI phase switching is supported on Windows host mode")
        self._assert_lease_held(lease_holder_id)
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
