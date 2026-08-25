param(
    [Parameter(Mandatory = $true)][string]$QwenBinaryPath,
    [Parameter(Mandatory = $true)][string]$QwenModelPath,
    [Parameter(Mandatory = $true)][string]$Qwen38BinaryPath,
    [Parameter(Mandatory = $true)][string]$Qwen38ModelPath,
    [Parameter(Mandatory = $true)][string]$PaddlePythonPath,
    [Parameter(Mandatory = $true)][string]$PaddleVlModelPath,
    [Parameter(Mandatory = $true)][string]$PaddleLayoutModelPath,
    [string]$OutputPath,
    [switch]$ReplaceExisting
)

. (Join-Path $PSScriptRoot "Common.ps1")

$repositoryRoot = Get-RepositoryRoot
if (-not $OutputPath) { $OutputPath = Join-Path $repositoryRoot ".env.local-ai" }
if (Test-Path -LiteralPath $OutputPath) {
    if (-not $ReplaceExisting) {
        throw "Refusing to overwrite existing local AI configuration: $OutputPath"
    }
    $backupDirectory = Join-Path $repositoryRoot ".local-ai\backups"
    New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null
    $backupPath = Join-Path $backupDirectory (
        "env-local-ai-before-hybrid-{0}.env" -f [DateTime]::UtcNow.ToString("yyyyMMddHHmmss")
    )
    Copy-Item -LiteralPath $OutputPath -Destination $backupPath
}
if (-not (Test-Path -LiteralPath $Qwen38BinaryPath)) { throw "Qwen3.8 llama-server binary was not found." }
if (-not (Test-Path -LiteralPath $Qwen38ModelPath)) { throw "Qwen3.8 GGUF model was not found." }
if (-not (Test-Path -LiteralPath $QwenBinaryPath -PathType Leaf)) { throw "Qwen3.6 llama-server binary was not found." }
if (-not (Test-Path -LiteralPath $QwenModelPath -PathType Leaf)) { throw "Qwen3.6 GGUF model was not found." }
if (-not (Test-Path -LiteralPath $PaddlePythonPath -PathType Leaf)) { throw "PaddleOCR Python runtime was not found." }
if (-not (Test-Path -LiteralPath $PaddleVlModelPath -PathType Container)) { throw "PaddleOCR-VL model directory was not found." }
if (-not (Test-Path -LiteralPath $PaddleLayoutModelPath -PathType Container)) { throw "Paddle layout model directory was not found." }
if (-not (Test-Path -LiteralPath (Join-Path $PaddleVlModelPath "model.safetensors") -PathType Leaf)) { throw "PaddleOCR-VL native model is incomplete (model.safetensors missing)." }
if (-not (Test-Path -LiteralPath (Join-Path $PaddleLayoutModelPath "inference.pdiparams") -PathType Leaf)) { throw "Paddle layout native model is incomplete (inference.pdiparams missing)." }

$mmprojPath = Join-Path (Split-Path $Qwen38ModelPath) "mmproj-Qwen3.8-27B-Q8_0.gguf"
if (-not (Test-Path -LiteralPath $mmprojPath)) { throw "Qwen3.8 mmproj file was not found beside the model." }

function New-LocalAiApiKey {
    $bytes = [byte[]]::new(32)
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
}
$qwenApiKey = New-LocalAiApiKey
$qwen38ApiKey = New-LocalAiApiKey
$paddleApiKey = New-LocalAiApiKey

$modelHash = (Get-FileHash -LiteralPath $Qwen38ModelPath -Algorithm SHA256).Hash.ToLowerInvariant()
$mmprojHash = (Get-FileHash -LiteralPath $mmprojPath -Algorithm SHA256).Hash.ToLowerInvariant()
$lines = @(
    "BRAIN_ALLOW_REAL_PROVIDERS=true"
    "LOCAL_QWEN_ENABLED=true"
    "LOCAL_QWEN_BASE_URL=http://127.0.0.1:8086/v1"
    "LOCAL_QWEN_MODEL=qwen3.6-35b-a3b-q4km"
    "LOCAL_QWEN_API_KEY=$qwenApiKey"
    "LOCAL_QWEN_BINARY_PATH=$QwenBinaryPath"
    "LOCAL_QWEN_MODEL_PATH=$QwenModelPath"
    "LOCAL_QWEN_CPU_MOE_LAYERS=28"
    "LOCAL_PADDLE_OCR_ENABLED=true"
    "LOCAL_PADDLE_OCR_BASE_URL=http://127.0.0.1:8090"
    "LOCAL_PADDLE_OCR_API_KEY=$paddleApiKey"
    "LOCAL_PADDLE_OCR_TIMEOUT_SECONDS=900"
    "LOCAL_PADDLE_OCR_MAX_IMAGE_BYTES=20971520"
    "LOCAL_PADDLE_OCR_MODEL=PaddleOCR-VL-1.6"
    "LOCAL_PADDLE_OCR_LAYOUT_MODEL=PP-DocLayoutV3"
    "LOCAL_PADDLE_OCR_PYTHON_PATH=$PaddlePythonPath"
    "LOCAL_PADDLE_OCR_VL_MODEL_PATH=$PaddleVlModelPath"
    "LOCAL_PADDLE_OCR_LAYOUT_MODEL_PATH=$PaddleLayoutModelPath"
    "LOCAL_PADDLE_OCR_DEVICE=gpu:0"
    "LOCAL_PADDLE_OCR_HOST=127.0.0.1"
    "LOCAL_PADDLE_OCR_PORT=8090"
    "LOCAL_QWEN38_ENABLED=true"
    "LOCAL_QWEN38_BASE_URL=http://127.0.0.1:8085/v1"
    "LOCAL_QWEN38_MODEL=qwen3.8-27b-q4km"
    "LOCAL_QWEN38_API_KEY=$qwen38ApiKey"
    "LOCAL_QWEN38_TIMEOUT_SECONDS=600"
    "LOCAL_QWEN38_BINARY_PATH=$Qwen38BinaryPath"
    "LOCAL_QWEN38_MODEL_PATH=$Qwen38ModelPath"
    "LOCAL_QWEN38_MODEL_SHA256=$modelHash"
    "LOCAL_QWEN38_MMPROJ_SHA256=$mmprojHash"
    "LOCAL_QWEN38_GPU_LAYERS=34"
    "LOCAL_QWEN38_FIT_TARGET_MIB="
    "LOCAL_QWEN38_THREADS=12"
    "LOCAL_QWEN38_THREADS_BATCH=12"
    "LOCAL_QWEN38_BATCH_SIZE=256"
    "LOCAL_QWEN38_UBATCH_SIZE=256"
    "LOCAL_QWEN38_CPU_MASK="
    "LOCAL_QWEN38_CPU_MASK_BATCH="
    "LOCAL_QWEN38_MTP_MODEL_PATH="
    "LOCAL_QWEN38_MTP_SHA256="
    "LOCAL_QWEN38_SPEC_DRAFT_TOKENS=0"
    "LOCAL_QWEN38_VISUAL_PREPARATION_ENABLED=false"
    "LOCAL_QWEN38_TRANSCRIPTION_ENABLED=true"
    "LOCAL_QWEN38_THINKING_REPAIR_ENABLED=false"
    "LOCAL_QWEN38_GRADING_ENABLED=false"
    "LOCAL_QWEN38_GRADING_REASONING_MODE=off"
    "LOCAL_QWEN38_MAX_VISUAL_CALLS=25"
    "LOCAL_REFERENCE_EXTRACTION_ENABLED=true"
    "LOCAL_REFERENCE_MAX_OCR_CALLS=20"
    "LOCAL_OCR_RENDER_DPI=300"
    "LOCAL_SCRIPT_PREPARATION_ENABLED=true"
    "LOCAL_SCRIPT_MAX_OCR_CALLS=25"
    "LOCAL_SINGLE_ANSWER_GRADING_ENABLED=true"
    "LOCAL_AI_PHASE_SWITCH_ENABLED=true"
    "COHORT_MODEL_GRADING_ENABLED=false"
    "COHORT_PROVIDER_RETRY_COUNT=0"
)
[IO.File]::WriteAllLines($OutputPath, $lines, [Text.UTF8Encoding]::new($false))
Write-Host "Created ignored hybrid local-AI configuration at $OutputPath"
Write-Host "PaddleOCR, Qwen3.6, and Qwen3.8 transcription rescue are enabled; cohort grading remains disabled."
