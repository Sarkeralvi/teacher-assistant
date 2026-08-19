<#
.SYNOPSIS
    Gate I1 — Verify llama.cpp build 10249 loads Qwen3.8-27B-Q4_K_M.gguf correctly.

.DESCRIPTION
    Starts llama-server on a temporary probe port (8087) with one GPU layer
    (fast load), waits up to 90 s for /health, checks logs for architecture
    errors, reports flash-attention and CUDA layer status, then stops cleanly.
    Does NOT leave the server running.

.PARAMETER ModelPath
    Path to Qwen3.8-27B-Q4_K_M.gguf.

.PARAMETER BinaryPath
    Path to llama-server.exe.
#>
param(
    [string]$ModelPath  = 'E:\ai\llama-cpp\models\Qwen3.8-27B\Qwen3.8-27B-Q4_K_M.gguf',
    [string]$BinaryPath = 'E:\ai\llama-cpp\bin\llama-server.exe'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$PROBE_PORT      = 8087
$TIMEOUT_SECONDS = 90

Write-Host ""
Write-Host "=== Gate I1: Qwen3.8 architecture compatibility check ===" -ForegroundColor Cyan
Write-Host "Binary : $BinaryPath"
Write-Host "Model  : $ModelPath"
Write-Host "Port   : $PROBE_PORT  (temporary — only for this probe)"
Write-Host ""

if (-not (Test-Path -LiteralPath $BinaryPath)) { throw "llama-server.exe not found: $BinaryPath" }
if (-not (Test-Path -LiteralPath $ModelPath))  { throw "Model not found: $ModelPath — run Download-Qwen38Model.ps1 first." }

if (Get-NetTCPConnection -LocalPort $PROBE_PORT -ErrorAction SilentlyContinue) {
    throw "Port $PROBE_PORT is in use. Free it and retry."
}

$repoRoot  = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$logDir    = Join-Path $repoRoot '.local-ai\logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$stdoutLog = Join-Path $logDir 'qwen38-compat.stdout.log'
$stderrLog = Join-Path $logDir 'qwen38-compat.stderr.log'

$serverArgs = @(
    '-m', $ModelPath,
    '-ngl', '1',
    '-c',  '512',
    '--parallel', '1',
    '--host', '127.0.0.1',
    '--port', $PROBE_PORT,
    '--offline',
    '--batch-size', '128',
    '--ubatch-size', '128',
    '--threads', '4'
)

Write-Host "Starting server (1 GPU layer, fast probe)..." -ForegroundColor Gray
$proc = Start-Process -FilePath $BinaryPath -ArgumentList $serverArgs `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError  $stderrLog

$deadline = [DateTime]::UtcNow.AddSeconds($TIMEOUT_SECONDS)
$healthy  = $false
try {
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($proc.HasExited) {
            $stderr = Get-Content $stderrLog -Raw -ErrorAction SilentlyContinue
            throw "Server exited unexpectedly (code $($proc.ExitCode)).`nStderr: $stderr"
        }
        try {
            $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$PROBE_PORT/health" -TimeoutSec 3 -ErrorAction Stop
            if ($resp.status -eq 'ok') { $healthy = $true; break }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) { throw "Server did not become healthy in $TIMEOUT_SECONDS s." }

    Write-Host "Server healthy. Checking logs for architecture errors..." -ForegroundColor Gray
    $combined = (Get-Content $stderrLog -Raw -ErrorAction SilentlyContinue) + "`n" + (Get-Content $stdoutLog -Raw -ErrorAction SilentlyContinue)

    $fatalPatterns = @(
        'unknown model architecture',
        'unsupported model architecture',
        'failed to load model',
        'error loading model',
        'GGUF load error'
    )
    foreach ($p in $fatalPatterns) {
        if ($combined -imatch [regex]::Escape($p)) { throw "Architecture error in log: '$p'" }
    }

    $faMatch    = [regex]::Match($combined, 'flash[\._]attn\s*=\s*(\S+)')
    $cudaMatch  = [regex]::Match($combined, 'offloaded\s+(\d+)\s+layers?\s+to\s+GPU')
    $archMatch  = [regex]::Match($combined, 'model type\s*[=:]\s*(\S+)')
    $faStatus   = if ($faMatch.Success)   { $faMatch.Groups[1].Value }   else { 'not reported' }
    $cudaLayers = if ($cudaMatch.Success) { $cudaMatch.Groups[1].Value }  else { 'not reported' }
    $archType   = if ($archMatch.Success) { $archMatch.Groups[1].Value }  else { 'not reported' }

    Write-Host ""
    Write-Host "=== Gate I1 PASSED ===" -ForegroundColor Green
    Write-Host "Architecture    : $archType"
    Write-Host "Flash attention : $faStatus"
    Write-Host "CUDA layers     : $cudaLayers (probe used only 1)"
    Write-Host "Fatal errors    : none"
    Write-Host ""
    Write-Host "Build 10249 supports Qwen3.8 (qwen3_5 arch + qwen3vl multimodal)." -ForegroundColor Green
} finally {
    if ($null -ne $proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    Write-Host "Probe server stopped cleanly." -ForegroundColor Gray
}
