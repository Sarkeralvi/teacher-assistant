<#
.SYNOPSIS
  Run Baidu Unlimited-OCR on one image and print the raw output, for direct
  comparison against what you see on the HuggingFace demo.

.DESCRIPTION
  No scoring, no fixtures, no bake-off math -- just the model's own reading of
  whatever image you point it at. CPU-only (franken_ocr), local, no GPU load,
  no network call beyond the model files already on disk.

.PARAMETER ImagePath
  Path to a PNG/JPG page or crop.

.PARAMETER CropMode
  'base' (default, single 1024px global view) or 'gundam' (dynamic-resolution
  tiling -- closer to what a hosted demo may use for full-page documents).

.EXAMPLE
  .\Test-UnlimitedOcr.ps1 -ImagePath "C:\path\to\page.png"

.EXAMPLE
  .\Test-UnlimitedOcr.ps1 -ImagePath "C:\path\to\page.png" -CropMode gundam
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath,

    [ValidateSet("base", "gundam")]
    [string]$CropMode = "base"
)

if (-not (Test-Path $ImagePath)) {
    Write-Error "Image not found: $ImagePath"
    exit 1
}

$focr = "$env:LOCALAPPDATA\Programs\focr\focr.exe"
if (-not (Test-Path $focr)) {
    Write-Error "focr is not installed at $focr. Run the franken_ocr installer first."
    exit 1
}

Write-Host "Running Unlimited-OCR (crop-mode=$CropMode) on: $ImagePath" -ForegroundColor Cyan
Write-Host ""
& $focr ocr $ImagePath --crop-mode $CropMode
