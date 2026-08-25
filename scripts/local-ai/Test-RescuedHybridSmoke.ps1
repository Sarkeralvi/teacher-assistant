param(
    [string]$ConfigPath,
    [switch]$AllowLocalPaddle,
    [switch]$AllowLocalQwen36,
    [switch]$AllowLocalQwen38Rescue
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "Common.ps1")
$repositoryRoot = Get-RepositoryRoot
if (-not $ConfigPath) { $ConfigPath = Join-Path $repositoryRoot ".env.local-ai" }
if (-not $AllowLocalPaddle -or -not $AllowLocalQwen36) {
    throw "Pass -AllowLocalPaddle and -AllowLocalQwen36 to authorize exactly one synthetic call each."
}
Import-LocalAiEnvironment -Path $ConfigPath
$pilotStatus = Join-Path $repositoryRoot "scripts\pilot\Get-TeacherPilotStatus.ps1"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $pilotStatus -RequireCore
if ($LASTEXITCODE -ne 0) {
    throw "The supported pilot stack must be healthy before the lease-backed smoke runs."
}
$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$arguments = @(
    "-m", "scripts.rescued_hybrid_smoke",
    "--allow-paddle",
    "--allow-qwen36",
    "--result-path", (Join-Path $repositoryRoot ".local-ai\logs\rescued-hybrid-smoke.json")
)
if ($AllowLocalQwen38Rescue) { $arguments += "--allow-qwen38-rescue" }

try {
    Push-Location (Join-Path $repositoryRoot "apps\api")
    try {
        $env:PYTHONPATH = "."
        & $python @arguments
        if ($LASTEXITCODE -ne 0) { throw "Rescued hybrid smoke failed." }
    } finally {
        Pop-Location
    }
} finally {
    foreach ($mode in @("PaddleOcr", "Qwen", "Qwen38")) {
        & (Join-Path $PSScriptRoot "Stop-LocalAi.ps1") -ConfigPath $ConfigPath -Mode $mode
    }
}
