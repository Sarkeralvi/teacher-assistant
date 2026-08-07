param(
    [Parameter(Mandatory = $true)][string]$QwenBinaryPath,
    [Parameter(Mandatory = $true)][string]$QwenModelPath,
    [Parameter(Mandatory = $true)][string]$OcrPythonPath,
    [Parameter(Mandatory = $true)][string]$OcrVlModelPath,
    [Parameter(Mandatory = $true)][string]$OcrLayoutModelPath,
    [string]$OutputPath
)

. (Join-Path $PSScriptRoot "Common.ps1")

$repositoryRoot = Get-RepositoryRoot
if (-not $OutputPath) {
    $OutputPath = Join-Path $repositoryRoot ".env.local-ai"
}
if (Test-Path -LiteralPath $OutputPath) {
    throw "Refusing to overwrite existing local AI configuration: $OutputPath"
}

function New-LocalApiKey {
    $randomBytes = [byte[]]::new(32)
    $randomNumberGenerator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $randomNumberGenerator.GetBytes($randomBytes)
    } finally {
        $randomNumberGenerator.Dispose()
    }
    return ([BitConverter]::ToString($randomBytes)).Replace("-", "").ToLowerInvariant()
}

$qwenApiKey = New-LocalApiKey
$ocrApiKey = New-LocalApiKey

$lines = @(
    "BRAIN_ALLOW_REAL_PROVIDERS=true"
    "LOCAL_QWEN_ENABLED=true"
    "LOCAL_QWEN_BASE_URL=http://127.0.0.1:8080/v1"
    "LOCAL_QWEN_MODEL=qwen3.6-35b-a3b-q4km"
    "LOCAL_QWEN_API_KEY=$qwenApiKey"
    "LOCAL_QWEN_BINARY_PATH=$QwenBinaryPath"
    "LOCAL_QWEN_MODEL_PATH=$QwenModelPath"
    "LOCAL_OCR_ENABLED=true"
    "LOCAL_OCR_BASE_URL=http://127.0.0.1:8090"
    "LOCAL_OCR_API_KEY=$ocrApiKey"
    "LOCAL_OCR_PYTHON_PATH=$OcrPythonPath"
    "LOCAL_OCR_VL_MODEL_PATH=$OcrVlModelPath"
    "LOCAL_OCR_LAYOUT_MODEL_PATH=$OcrLayoutModelPath"
    "LOCAL_OCR_HOST=127.0.0.1"
    "LOCAL_OCR_PORT=8090"
    "LOCAL_OCR_MAX_IMAGE_BYTES=20971520"
    "COHORT_MODEL_GRADING_ENABLED=false"
    "COHORT_MAX_PROVIDER_CALLS=25"
    "COHORT_PROVIDER_RETRY_COUNT=0"
)
[IO.File]::WriteAllLines($OutputPath, $lines, [Text.UTF8Encoding]::new($false))
Write-Host "Created ignored local AI configuration at $OutputPath"
Write-Host "Cohort model grading remains disabled until you explicitly enable it."
