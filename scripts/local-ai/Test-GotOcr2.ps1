<#
.SYNOPSIS
  Run GOT-OCR2.0 on one image and print the raw output.

.DESCRIPTION
  No scoring, no fixtures, no bake-off math -- just the model's own reading of
  whatever image you point it at. This is the OCR bake-off's math specialist
  (0.122-0.135 CER on typeset math, beating both RapidOCR and Tesseract; see
  docs/LOCAL_AI_RUNBOOK.md). Two backends:

    -Device cpu (default)  via the franken_ocr CLI, plain mode, ~7-17s/page
    -Device gpu             via transformers on CUDA, ~1-9s/page, needs torch

  -Formula switches to structured LaTeX/formula mode. Use it ONLY on genuine
  math/formula images -- on ordinary handwriting it degenerates into repeating
  unrelated glyphs (this was diagnosed and documented during the bake-off).

.PARAMETER ImagePath
  Path to a PNG/JPG page or crop.

.EXAMPLE
  .\Test-GotOcr2.ps1 -ImagePath "C:\path\to\page.png"

.EXAMPLE
  .\Test-GotOcr2.ps1 -ImagePath "C:\path\to\formula.png" -Device gpu -Formula
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath,

    [ValidateSet("cpu", "gpu")]
    [string]$Device = "cpu",

    [switch]$Formula
)

if (-not (Test-Path $ImagePath)) {
    Write-Error "Image not found: $ImagePath"
    exit 1
}

if ($Device -eq "cpu") {
    $focr = "$env:LOCALAPPDATA\Programs\focr\focr.exe"
    if (-not (Test-Path $focr)) {
        Write-Error "focr is not installed at $focr. Run the franken_ocr installer first."
        exit 1
    }
    $modeLabel = if ($Formula) { "formula/LaTeX" } else { "plain" }
    Write-Host "Running GOT-OCR2 (CPU, $modeLabel mode) on: $ImagePath" -ForegroundColor Cyan
    Write-Host ""
    $args = @("ocr", $ImagePath, "--model", "got-ocr2.int8.focrq")
    if ($Formula) { $args += @("--task", "formula") }
    & $focr @args
} else {
    $repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    $script = Join-Path $repoRoot "scripts\local-ai\got_ocr2_gpu.py"
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    $python = if (Test-Path $venvPython) { $venvPython } else { "python" }

    $modeLabel = if ($Formula) { "formula/LaTeX" } else { "plain" }
    Write-Host "Running GOT-OCR2 (GPU, $modeLabel mode) on: $ImagePath" -ForegroundColor Cyan
    Write-Host ""
    $pyArgs = @($script, $ImagePath)
    if ($Formula) { $pyArgs += "--formula" }
    & $python @pyArgs
}
