<#
.SYNOPSIS
    Gate I4 — Visual transcription smoke test against real submission images.

.DESCRIPTION
    Sends the strict verbatim-transcription prompt to a running Qwen3.8 server
    (port 8085) for each supplied image.  Captures raw Markdown/LaTeX from
    /v1/chat/completions.  Writes raw responses to:
        .local-ai\runtime\qwen38-transcription-{timestamp}.json  (git-ignored)

    NEVER performs automated pass/fail.  Teacher must review raw output manually
    before Gate I5 is enabled.

    The server must already be running (started by Start-Qwen38Smoke.ps1 or
    Start-LocalAi.ps1 -Mode Qwen38).  This script does NOT start or stop it.

.PARAMETER ApiKey
    Bearer token matching LOCAL_QWEN38_API_KEY.

.PARAMETER ImagePaths
    Array of PNG/JPEG paths to test.  Paths must exist locally.
    Example:  @('C:\path\to\1a_i.png', 'C:\path\to\1b_i.png', ...)

.PARAMETER Port
    Server port.  Default 8085.
#>
param(
    [Parameter(Mandatory = $true)][string]$ApiKey,
    [Parameter(Mandatory = $true)][string[]]$ImagePaths,
    [int]$Port = 8085
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ALIAS      = 'qwen3.8-27b-q4km'
$HOST_ADDR  = '127.0.0.1'

$TRANSCRIPTION_PROMPT = @"
Perform strict verbatim transcription of this handwritten student answer.
Do not solve, correct, complete, simplify, summarize, or reinterpret anything.
Preserve every written mistake, line order, numeral, decimal point, fraction,
conditional bar, complement bar, intersection, unit and crossed-out item.
Use LaTeX for mathematics. If a glyph is ambiguous, return bounded alternatives
marked uncertain. Never infer a character from arithmetic consistency.
"@

Write-Host ""
Write-Host "=== Gate I4: Qwen3.8 visual transcription smoke ===" -ForegroundColor Cyan
Write-Host "Server : http://$HOST_ADDR`:$PORT"
Write-Host "Images : $($ImagePaths.Count)"
Write-Host ""

# Verify server is reachable
try {
    $health = Invoke-RestMethod -Uri "http://$HOST_ADDR`:$PORT/health" -TimeoutSec 5 -ErrorAction Stop
    if ($health.status -ne 'ok') { throw "Server health not ok: $($health.status)" }
} catch {
    throw "Cannot reach Qwen3.8 server on port $PORT. Start it with Start-LocalAi.ps1 -Mode Qwen38 first."
}

# Verify alias
$models = Invoke-RestMethod -Uri "http://$HOST_ADDR`:$PORT/v1/models" `
    -Headers @{ Authorization = "Bearer $ApiKey" } -TimeoutSec 10
if (-not (@($models.data.id) -contains $ALIAS)) {
    throw "Server does not report alias '$ALIAS'. Wrong model loaded?"
}

$repoRoot   = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtimeDir = Join-Path $repoRoot '.local-ai\runtime'
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

$headers  = @{ Authorization = "Bearer $ApiKey"; 'Content-Type' = 'application/json' }
$results  = @()

foreach ($imgPath in $ImagePaths) {
    if (-not (Test-Path -LiteralPath $imgPath)) {
        Write-Warning "Image not found, skipping: $imgPath"
        continue
    }

    # Determine MIME type
    $ext = [System.IO.Path]::GetExtension($imgPath).ToLower()
    $mime = switch ($ext) {
        '.png'  { 'image/png' }
        '.jpg'  { 'image/jpeg' }
        '.jpeg' { 'image/jpeg' }
        default { throw "Unsupported image format: $ext (only PNG/JPEG accepted)" }
    }

    # MIME magic-byte check — never send HTML errors as images
    $hdr = [byte[]]::new(8)
    $fs  = [System.IO.File]::OpenRead($imgPath)
    try { [void]$fs.Read($hdr, 0, 8) } finally { $fs.Close() }
    $isPng  = $hdr[0] -eq 0x89 -and $hdr[1] -eq 0x50 -and $hdr[2] -eq 0x4E -and $hdr[3] -eq 0x47
    $isJpeg = $hdr[0] -eq 0xFF -and $hdr[1] -eq 0xD8
    if ($mime -eq 'image/png'  -and -not $isPng)  { throw "File claims PNG but magic bytes wrong: $imgPath" }
    if ($mime -eq 'image/jpeg' -and -not $isJpeg) { throw "File claims JPEG but magic bytes wrong: $imgPath" }

    # Compute image SHA256 for audit log
    $imgHash = (Get-FileHash -LiteralPath $imgPath -Algorithm SHA256).Hash.ToLower()

    # Encode as data URL
    $imgBytes   = [System.IO.File]::ReadAllBytes($imgPath)
    $b64        = [Convert]::ToBase64String($imgBytes)
    $dataUrl    = "data:$mime;base64,$b64"

    $body = @{
        model    = $ALIAS
        messages = @(
            @{
                role    = 'user'
                content = @(
                    @{ type = 'text';      text     = $TRANSCRIPTION_PROMPT }
                    @{ type = 'image_url'; image_url = @{ url = $dataUrl } }
                )
            }
        )
        max_tokens = 2048
        stream     = $false
        temperature = 0.0
        chat_template_kwargs = @{ enable_thinking = $false; preserve_thinking = $false }
    } | ConvertTo-Json -Depth 8

    $label = [System.IO.Path]::GetFileNameWithoutExtension($imgPath)
    Write-Host "Processing: $label ..." -ForegroundColor Gray

    $t0   = [DateTime]::UtcNow
    $resp = Invoke-RestMethod -Uri "http://$HOST_ADDR`:$PORT/v1/chat/completions" `
        -Method Post -Body $body -Headers $headers -TimeoutSec 300
    $latency = [math]::Round(([DateTime]::UtcNow - $t0).TotalMilliseconds)

    $usage   = $resp.usage
    $content = $resp.choices[0].message.content
    if ([string]::IsNullOrWhiteSpace($content)) { throw "Visual smoke returned empty content for $label" }
    $reasoning = if ($resp.choices[0].message.PSObject.Properties.Match('reasoning_content').Count -gt 0) {
        [string]$resp.choices[0].message.reasoning_content
    } else {
        ""
    }
    if (-not [string]::IsNullOrWhiteSpace($reasoning)) { throw "Visual smoke returned reasoning content for $label" }
    $finishR = $resp.choices[0].finish_reason

    Write-Host "  Latency    : $latency ms" -ForegroundColor Green
    Write-Host "  Finish     : $finishR"
    Write-Host "  Tokens     : prompt=$($usage.prompt_tokens) gen=$($usage.completion_tokens)"
    Write-Host "  Output:"
    Write-Host ($content | ForEach-Object { "    $_" })
    Write-Host ""

    $results += [ordered]@{
        label              = $label
        image_path         = $imgPath
        image_sha256       = $imgHash
        image_mime         = $mime
        latency_ms         = $latency
        finish_reason      = $finishR
        prompt_tokens      = $usage.prompt_tokens
        completion_tokens  = $usage.completion_tokens
        raw_transcription  = $content   # raw Markdown/LaTeX — teacher reviews
    }
}

$timestamp  = Get-Date -Format 'yyyyMMddHHmmss'
$reportPath = Join-Path $runtimeDir "qwen38-transcription-$timestamp.json"

$report = [ordered]@{
    schema_version = 1
    gate           = 'I4'
    timestamp_utc  = ([DateTime]::UtcNow).ToString('o')
    alias          = $ALIAS
    prompt_version = 'verbatim-transcription-v1'
    image_count    = $results.Count
    results        = $results
    teacher_review = 'REQUIRED before enabling Gate I5'
}
$report | ConvertTo-Json -Depth 6 | Set-Content $reportPath -Encoding UTF8

Write-Host "=== Gate I4 raw output written ===" -ForegroundColor Yellow
Write-Host "Report : $reportPath"
Write-Host ""
Write-Host "MANUAL REVIEW REQUIRED:" -ForegroundColor Yellow
Write-Host "  1. Open $reportPath"
Write-Host "  2. Inspect raw_transcription for each image"
Write-Host "  3. Verify: fractions, bars, intersection symbols, numerals preserved"
Write-Host "  4. Verify: no solving, correcting, or reinterpreting"
Write-Host "  5. Only after teacher sign-off: enable LOCAL_QWEN38_ENABLED=true"
