param(
    [Parameter(Mandatory = $true)][string]$Qwen38BinaryPath,
    [Parameter(Mandatory = $true)][string]$Qwen38ModelPath,
    [string]$OutputPath
)

. (Join-Path $PSScriptRoot "Common.ps1")

$repositoryRoot = Get-RepositoryRoot
if (-not $OutputPath) { $OutputPath = Join-Path $repositoryRoot ".env.local-ai" }
if (Test-Path -LiteralPath $OutputPath) {
    throw "Refusing to overwrite existing local AI configuration: $OutputPath"
}
if (-not (Test-Path -LiteralPath $Qwen38BinaryPath)) { throw "Qwen3.8 llama-server binary was not found." }
if (-not (Test-Path -LiteralPath $Qwen38ModelPath)) { throw "Qwen3.8 GGUF model was not found." }

$mmprojPath = Join-Path (Split-Path $Qwen38ModelPath) "mmproj-Qwen3.8-27B-Q8_0.gguf"
if (-not (Test-Path -LiteralPath $mmprojPath)) { throw "Qwen3.8 mmproj file was not found beside the model." }

$randomBytes = [byte[]]::new(32)
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($randomBytes) } finally { $rng.Dispose() }
$apiKey = ([BitConverter]::ToString($randomBytes)).Replace("-", "").ToLowerInvariant()

$modelHash = (Get-FileHash -LiteralPath $Qwen38ModelPath -Algorithm SHA256).Hash.ToLowerInvariant()
$mmprojHash = (Get-FileHash -LiteralPath $mmprojPath -Algorithm SHA256).Hash.ToLowerInvariant()
$lines = @(
    "BRAIN_ALLOW_REAL_PROVIDERS=true"
    "LOCAL_QWEN_ENABLED=false"
    "LOCAL_QWEN38_ENABLED=true"
    "LOCAL_QWEN38_BASE_URL=http://127.0.0.1:8085/v1"
    "LOCAL_QWEN38_MODEL=qwen3.8-27b-q4km"
    "LOCAL_QWEN38_API_KEY=$apiKey"
    "LOCAL_QWEN38_TIMEOUT_SECONDS=600"
    "LOCAL_QWEN38_BINARY_PATH=$Qwen38BinaryPath"
    "LOCAL_QWEN38_MODEL_PATH=$Qwen38ModelPath"
    "LOCAL_QWEN38_MODEL_SHA256=$modelHash"
    "LOCAL_QWEN38_MMPROJ_SHA256=$mmprojHash"
    "LOCAL_QWEN38_VISUAL_PREPARATION_ENABLED=false"
    "LOCAL_QWEN38_GRADING_ENABLED=false"
    "LOCAL_QWEN38_GRADING_REASONING_MODE=off"
    "LOCAL_QWEN38_MAX_VISUAL_CALLS=25"
    "LOCAL_REFERENCE_EXTRACTION_ENABLED=false"
    "LOCAL_SCRIPT_PREPARATION_ENABLED=false"
    "LOCAL_SINGLE_ANSWER_GRADING_ENABLED=false"
    "COHORT_MODEL_GRADING_ENABLED=false"
    "COHORT_PROVIDER_RETRY_COUNT=0"
)
[IO.File]::WriteAllLines($OutputPath, $lines, [Text.UTF8Encoding]::new($false))
Write-Host "Created ignored Qwen3.8 local configuration at $OutputPath"
Write-Host "Visual preparation and grading remain disabled until an operator explicitly enables them."
