<#
.SYNOPSIS
Temporarily enables only one named local curated-evaluation grading run.

.DESCRIPTION
This script changes environment variables in the current PowerShell process;
it does not edit .env.local-ai, start a model, start the web application, or
enable cohort grading in the already-running teacher-pilot API process.

The evaluation CLI refuses grading unless LOCAL_CURATED_EVALUATION_RUN_ID
matches its immutable run manifest. Use Disable-LocalCuratedEvaluation.ps1
after the stage completes or fails.
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z][a-z0-9_]{2,63}$')]
    [string]$RunId
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "..\pilot\Common.ps1")
. (Join-Path $PSScriptRoot "..\local-ai\Common.ps1")

$paths = Get-PilotPaths
Assert-PilotRuntime -Paths $paths
$localAiConfig = Join-Path $paths.RepositoryRoot ".env.local-ai"
Import-LocalAiEnvironment -Path $localAiConfig

$expectedDatabaseName = "teacher_assistant_eval_$RunId"
if (
    [string]::IsNullOrWhiteSpace($env:DATABASE_URL) -or
    -not $env:DATABASE_URL.EndsWith("/$expectedDatabaseName", [StringComparison]::Ordinal)
) {
    throw (
        "DATABASE_URL must already point to $expectedDatabaseName. " +
        "Run New-LocalCuratedEvaluationDatabase.ps1 first in this PowerShell session."
    )
}

if ($env:BRAIN_ALLOW_REAL_PROVIDERS -ne "true") {
    throw "BRAIN_ALLOW_REAL_PROVIDERS must be true in ignored local configuration."
}
if ($env:LOCAL_QWEN_ENABLED -ne "true" -or $env:LOCAL_QWEN38_ENABLED -ne "true") {
    throw "Both local Qwen3.6 and Qwen3.8 providers must be enabled for the grading bake-off."
}
if ($env:LOCAL_QWEN38_VISUAL_PREPARATION_ENABLED -ne "true") {
    throw "Qwen3.8 visual preparation must be enabled for the curated evaluation."
}
if ($env:LOCAL_QWEN38_GRADING_ENABLED -ne "true") {
    throw "Qwen3.8 text grading must be enabled for the grading bake-off."
}

$env:COHORT_MODEL_GRADING_ENABLED = "true"
$env:LOCAL_CURATED_EVALUATION_RUN_ID = $RunId

Write-Host "Local curated evaluation scope enabled for: $RunId"
Write-Host "This applies only to this PowerShell session and the evaluation CLI it starts."
