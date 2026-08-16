param(
    [Parameter(Mandatory = $true)][string]$ImagePath,
    [string]$ConfigPath,
    [switch]$IncludeVl
)

. (Join-Path $PSScriptRoot "Common.ps1")

$repositoryRoot = Get-RepositoryRoot
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repositoryRoot ".env.local-ai"
}
Import-LocalAiEnvironment -Path $ConfigPath
$resolvedImage = (Resolve-Path -LiteralPath $ImagePath -ErrorAction Stop).Path
$extension = [IO.Path]::GetExtension($resolvedImage).ToLowerInvariant()
$contentType = if ($extension -eq ".png") { "image/png" } elseif (
    $extension -in @(".jpg", ".jpeg")
) { "image/jpeg" } else { throw "Smoke image must be PNG or JPEG." }
$apiKey = Assert-RequiredEnvironmentValue -Name "LOCAL_OCR_API_KEY"
$auth = @{ Authorization = "Bearer $apiKey" }
$health = Invoke-RestMethod -Uri "http://127.0.0.1:8090/health" `
    -Headers $auth -TimeoutSec 10
$expectedModels = @(
    "PaddleOCR-VL-1.6",
    "PP-DocLayoutV3",
    "PP-OCRv6_medium_det",
    "PP-OCRv6_medium_rec"
)
$reportedModels = @(
    $health.models.PSObject.Properties.Value |
        ForEach-Object { @($_.model, $_.layout_model) } |
        Where-Object { $_ }
)
foreach ($expectedModel in $expectedModels) {
    if ($expectedModel -notin $reportedModels) {
        throw "OCR health model identity mismatch: $expectedModel"
    }
}

function Invoke-SmokeOcr([string]$Engine, [string]$Prompt, [string]$RequestSuffix) {
    $headers = @{
        Authorization = "Bearer $apiKey"
        "X-Request-ID" = "operator-rescue-smoke-$RequestSuffix"
        "X-OCR-Mode" = "answer_region"
        "X-OCR-Prompt-Label" = $Prompt
        "X-OCR-Engine" = $Engine
        "X-OCR-Preprocessing-Profile" = "math_handwriting_rescue"
    }
    return Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8090/v1/ocr" `
        -Headers $headers -ContentType $contentType -InFile $resolvedImage -TimeoutSec 300
}

$ppocr = Invoke-SmokeOcr -Engine "ppocr_v6" -Prompt "ocr" -RequestSuffix "ppocr"
if ($ppocr.engine -ne "ppocr_v6" -or $ppocr.model -ne "PP-OCRv6_medium_rec") {
    throw "PP-OCRv6 smoke returned the wrong model identity."
}
$vl = $null
if ($IncludeVl) {
    $vl = Invoke-SmokeOcr -Engine "paddleocr_vl" -Prompt "formula" -RequestSuffix "vl"
    if ($vl.engine -ne "paddleocr_vl" -or $vl.model -ne "PaddleOCR-VL-1.6") {
        throw "PaddleOCR-VL smoke returned the wrong model identity."
    }
}

[pscustomobject]@{
    Status = $health.status
    Device = $health.device
    Models = ($reportedModels -join ", ")
    PpOcrBlockCount = @($ppocr.blocks).Count
    PpOcrLatencyMs = $ppocr.latency_ms
    PaddleOcrVlCalled = [bool]$IncludeVl
    PaddleOcrVlBlockCount = if ($vl) { @($vl.blocks).Count } else { 0 }
    PaddleOcrVlLatencyMs = if ($vl) { $vl.latency_ms } else { 0 }
} | Format-List
