<#
.SYNOPSIS
Fail-closes local curated-evaluation grading in the current PowerShell session.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$env:COHORT_MODEL_GRADING_ENABLED = "false"
Remove-Item Env:LOCAL_CURATED_EVALUATION_RUN_ID -ErrorAction SilentlyContinue

Write-Host "Local curated evaluation grading scope is disabled for this PowerShell session."
