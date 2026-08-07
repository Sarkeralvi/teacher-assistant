param([string]$ConfigPath)

. (Join-Path $PSScriptRoot "Common.ps1")

$repositoryRoot = Get-RepositoryRoot
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repositoryRoot ".env.local-ai"
}
Import-LocalAiEnvironment -Path $ConfigPath

$qwenBinary = Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN_BINARY_PATH"
$qwenModel = Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN_MODEL_PATH"
$ocrPython = Assert-RequiredEnvironmentValue -Name "LOCAL_OCR_PYTHON_PATH"
$ocrVlModel = Assert-RequiredEnvironmentValue -Name "LOCAL_OCR_VL_MODEL_PATH"
$ocrLayoutModel = Assert-RequiredEnvironmentValue -Name "LOCAL_OCR_LAYOUT_MODEL_PATH"
$null = Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN_API_KEY"
$null = Assert-RequiredEnvironmentValue -Name "LOCAL_OCR_API_KEY"

$requiredFiles = @(
    $qwenBinary,
    $qwenModel,
    $ocrPython,
    (Join-Path $ocrVlModel "model.safetensors"),
    (Join-Path $ocrLayoutModel "inference.pdiparams")
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
& $ocrPython -c "import paddleocr, paddlex, paddle; from paddleocr import PaddleOCRVL; print(paddleocr.__version__, paddlex.__version__, paddle.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw "PaddleOCR Python environment check failed."
}

foreach ($port in @(8080, 8090)) {
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
$configuredOcrDevice = if ($env:LOCAL_OCR_DEVICE) { $env:LOCAL_OCR_DEVICE } else { "cpu" }
Write-Host "Configured OCR device: $configuredOcrDevice; maximum concurrency: 1"
