param([string]$ConfigPath)

. (Join-Path $PSScriptRoot "Common.ps1")

$repositoryRoot = Get-RepositoryRoot
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repositoryRoot ".env.local-ai"
}
Import-LocalAiEnvironment -Path $ConfigPath

$qwenBinary = Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN_BINARY_PATH"
$qwenModel = Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN_MODEL_PATH"
$null = Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN_API_KEY"

$requiredFiles = @(
    $qwenBinary,
    $qwenModel
)
foreach ($requiredFile in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required local AI file is missing: $requiredFile"
    }
}

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$versionOutput = & $qwenBinary --version 2>&1 | ForEach-Object { $_.ToString() }
$versionExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($versionExitCode -ne 0) {
    throw "llama-server version check failed."
}

foreach ($port in @(8080)) {
    $listeners = @(Get-LocalAiListenerInfo -Port $port)
    if ($listeners.Count -gt 0) {
        $binding = if (@($listeners | Where-Object { -not $_.IsLoopback }).Count -gt 0) {
            "an unsafe non-loopback binding"
        } else {
            "an existing loopback binding"
        }
        throw "Port $port already has $binding. Stop or identify that process before startup."
    }
}

Write-Host "Local AI preflight passed."
Write-Host "llama.cpp: $($versionOutput | Select-Object -First 1)"
Write-Host "Qwen model alias: $env:LOCAL_QWEN_MODEL"
