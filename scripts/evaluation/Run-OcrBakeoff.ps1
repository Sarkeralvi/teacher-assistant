<#
.SYNOPSIS
    Run the offline tier-1 OCR engine bake-off.

.DESCRIPTION
    Measures candidate OCR engines against teacher-labelled fixtures so the
    tier-1 engine is chosen from data rather than assertion.

    Offline by default. The qwen38_vision arm makes real provider calls and is
    refused unless -AuthorizeProviderCalls is passed; it exists to give the new
    pipeline an accuracy ceiling and latency baseline to be compared against.

    Fixtures and results live under gitignored data\evaluation\. Nothing here
    writes an image, a transcription, or a per-page result into the repository.

.PARAMETER FixturesDir
    Directory holding fixtures.json and its images.

.PARAMETER Engines
    Comma-separated arms. Default runs the offline arms only.

.PARAMETER AuthorizeProviderCalls
    Allow arms that call a real model. Capped by -MaxProviderCalls.
#>
param(
    [Parameter(Mandatory = $true)][string]$FixturesDir,
    [string]$Engines = "rapidocr_ppocrv5,rapidocr_ppocrv6,tesseract",
    [switch]$AuthorizeProviderCalls,
    [int]$MaxProviderCalls = 6,
    [string]$OutFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Repository virtual environment was not found at $python"
}
if (-not (Test-Path -LiteralPath $FixturesDir -PathType Container)) {
    throw "Fixtures directory was not found: $FixturesDir"
}

$arguments = @(
    "-m", "packages.evaluation.ocr_engine_bakeoff",
    "--fixtures", $FixturesDir,
    "--engines", $Engines,
    "--max-provider-calls", "$MaxProviderCalls"
)
if ($AuthorizeProviderCalls) { $arguments += "--i-authorize-provider-calls" }
if ($OutFile) { $arguments += @("--out", $OutFile) }

Push-Location (Join-Path $repositoryRoot "apps\api")
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "OCR bake-off failed with exit code $LASTEXITCODE." }
} finally {
    Pop-Location
}
