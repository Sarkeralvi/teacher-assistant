param(
    [string]$ConfigPath,
    [ValidateSet("Qwen", "Qwen38")]
    [string]$Mode = "Qwen"
)

. (Join-Path $PSScriptRoot "Common.ps1")

$repositoryRoot = Get-RepositoryRoot
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repositoryRoot ".env.local-ai"
}
Import-LocalAiEnvironment -Path $ConfigPath

$definition = Get-LocalAiServiceDefinition -Mode $Mode
$port = $definition.Port
$alias = $definition.Alias
$qwenBinary = Assert-RequiredEnvironmentValue -Name $definition.BinaryVariable
$qwenModel = Assert-RequiredEnvironmentValue -Name $definition.ModelVariable
$null = Assert-RequiredEnvironmentValue -Name $definition.KeyVariable

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

foreach ($port in @($port)) {
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
Write-Host "Qwen model alias: $alias"
