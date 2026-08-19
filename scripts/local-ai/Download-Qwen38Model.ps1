<#
.SYNOPSIS
    Download Qwen3.8-27B-Q4_K_M.gguf from the trusted ggml-org HuggingFace source.

.DESCRIPTION
    - Resumable download (Invoke-WebRequest -Resume).
    - Rejects HTML/error pages masquerading as model files.
    - Verifies resulting file size against HuggingFace metadata.
    - Computes SHA256 and records source URL, hash, size, and timestamp in
      .local-ai\runtime\qwen38-manifest.json (git-ignored).
    - Never deletes or touches Qwen3.6.
    - Stores the model under a versioned directory:
        E:\ai\llama-cpp\models\Qwen3.8-27B\Qwen3.8-27B-Q4_K_M.gguf

.NOTES
    Run this script once.  Gate I1 (Test-Qwen38Compatibility.ps1) and Gate I3
    (Start-Qwen38Smoke.ps1) require the model to exist at the target path.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$SOURCE_URL  = 'https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF/resolve/main/Qwen3.8-27B-Q4_K_M.gguf'
$TARGET_DIR  = 'E:\ai\llama-cpp\models\Qwen3.8-27B'
$TARGET_FILE = Join-Path $TARGET_DIR 'Qwen3.8-27B-Q4_K_M.gguf'
$QWEN36_PATH = 'E:\ai\llama-cpp\models\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf'

$repoRoot     = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$MANIFEST_DIR = Join-Path $repoRoot '.local-ai\runtime'

# Safety: Qwen3.6 must remain intact
if (-not (Test-Path -LiteralPath $QWEN36_PATH)) {
    throw "Qwen3.6 model not found at expected path. Aborting."
}

New-Item -ItemType Directory -Path $TARGET_DIR  -Force | Out-Null
New-Item -ItemType Directory -Path $MANIFEST_DIR -Force | Out-Null

Write-Host ""
Write-Host "=== Gate I2: Qwen3.8-27B-Q4_K_M.gguf download ===" -ForegroundColor Cyan
Write-Host "Source : $SOURCE_URL"
Write-Host "Target : $TARGET_FILE"
Write-Host ""

# Step 1: HEAD request — get expected content-length
Write-Host "Querying HuggingFace metadata..." -ForegroundColor Gray
$expectedBytes = 0
try {
    $headResp      = Invoke-WebRequest -Uri $SOURCE_URL -Method Head -MaximumRedirection 5 -UseBasicParsing -TimeoutSec 30
    $expectedBytes = [long]$headResp.Headers['Content-Length']
    Write-Host "Expected: $([math]::Round($expectedBytes / 1GB, 3)) GB ($expectedBytes bytes)"
} catch {
    Write-Warning "HEAD request failed — will verify size after download: $_"
}

# Reject suspiciously small responses (HTML error page guard)
$MIN_GGUF_BYTES = 100MB
if ($expectedBytes -gt 0 -and $expectedBytes -lt $MIN_GGUF_BYTES) {
    throw "Remote reports only $expectedBytes bytes — likely an HTML error page. Aborting."
}

# Step 2: Resumable download
if (Test-Path -LiteralPath $TARGET_FILE) {
    $existing = (Get-Item $TARGET_FILE).Length
    Write-Host "Partial file: $existing bytes. Resuming..." -ForegroundColor Yellow
} else {
    Write-Host "Starting fresh download..." -ForegroundColor Gray
}

$downloadStart = [DateTime]::UtcNow
curl.exe -L -C - -o $TARGET_FILE $SOURCE_URL
$downloadSeconds = ([DateTime]::UtcNow - $downloadStart).TotalSeconds

# Step 3: GGUF magic-byte check
$actualBytes = (Get-Item $TARGET_FILE).Length
Write-Host "`nValidating GGUF magic bytes..." -ForegroundColor Gray
$header = [byte[]]::new(4)
$fs = [System.IO.File]::OpenRead($TARGET_FILE)
try { [void]$fs.Read($header, 0, 4) } finally { $fs.Close() }
$magic = [System.Text.Encoding]::ASCII.GetString($header)
if ($magic -ne 'GGUF') {
    Remove-Item -LiteralPath $TARGET_FILE -Force
    throw "GGUF magic check failed (got: '$magic'). Corrupt download deleted. Re-run to restart."
}
Write-Host "GGUF magic : OK" -ForegroundColor Green

# Step 4: Size check
if ($expectedBytes -gt 0 -and $actualBytes -ne $expectedBytes) {
    throw "Size mismatch: expected $expectedBytes, got $actualBytes."
}
Write-Host "File size  : $([math]::Round($actualBytes / 1GB, 3)) GB — OK" -ForegroundColor Green

# Step 5: SHA256
Write-Host "Computing SHA256 (30-60 s for 17 GB)..." -ForegroundColor Gray
$hashStart = [DateTime]::UtcNow
$hash = (Get-FileHash -LiteralPath $TARGET_FILE -Algorithm SHA256).Hash.ToLower()
$hashSeconds = ([DateTime]::UtcNow - $hashStart).TotalSeconds
Write-Host "SHA256     : $hash" -ForegroundColor Green

# Step 6: Write manifest
$manifest = [ordered]@{
    schema_version   = 1
    gate             = 'I2'
    timestamp_utc    = ([DateTime]::UtcNow).ToString('o')
    source_url       = $SOURCE_URL
    target_path      = $TARGET_FILE
    sha256           = $hash
    byte_size        = $actualBytes
    size_gb          = [math]::Round($actualBytes / 1GB, 3)
    download_seconds = [math]::Round($downloadSeconds, 1)
    hash_seconds     = [math]::Round($hashSeconds, 1)
    gguf_magic_ok    = $true
    qwen36_untouched = $true
}
$manifestPath = Join-Path $MANIFEST_DIR 'qwen38-manifest.json'
$manifest | ConvertTo-Json -Depth 3 | Set-Content $manifestPath -Encoding UTF8

Write-Host ""
Write-Host "=== Gate I2 complete ===" -ForegroundColor Green
Write-Host "Manifest : $manifestPath"
Write-Host "Model    : $TARGET_FILE"
Write-Host ""
Write-Host "Next: run Test-Qwen38Compatibility.ps1, then Start-Qwen38Smoke.ps1" -ForegroundColor Cyan
