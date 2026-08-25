"""Opt-in host smoke for the rescued Paddle -> Qwen3.6 architecture."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_RESCUED_HYBRID_HOST_SMOKE") != "1",
    reason="set RUN_RESCUED_HYBRID_HOST_SMOKE=1 for three authorized synthetic calls",
)


def test_rescued_hybrid_host_smoke() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    script = repository_root / "scripts" / "local-ai" / "Test-RescuedHybridSmoke.ps1"
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-AllowLocalPaddle",
            "-AllowLocalQwen36",
            "-AllowLocalQwen38Rescue",
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert result.returncode == 0, (result.stdout + result.stderr)[-4000:]
    assert '"final_grade_created": false' in result.stdout
    assert '"paddle": 1' in result.stdout
    assert '"qwen36": 1' in result.stdout
    assert '"qwen38_rescue": 1' in result.stdout
