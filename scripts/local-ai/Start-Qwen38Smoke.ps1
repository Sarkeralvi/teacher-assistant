<#
.SYNOPSIS
    Gate I3 — Start Qwen3.8-27B on port 8085, measure performance, stop.

.DESCRIPTION
    Starts llama-server with hybrid GPU/RAM offload (40 GPU layers initially),
    runs three sequential /v1/chat/completions calls to measure stability,
    captures VRAM delta via nvidia-smi, records all metrics to
    .local-ai\runtime\qwen38-smoke-{timestamp}.json (git-ignored), then stops.

    The server is NEVER left running after this script exits.
    Use Start-LocalAi.ps1 -Mode Qwen38 for production phase management.

.PARAMETER ApiKey
    Bearer token for the server.  Must match LOCAL_QWEN38_API_KEY in .env.local-ai.

.PARAMETER NglLayers
    Number of layers to offload to GPU.  Default 40 (conservative first run).
    Raise after verifying no OOM.
#>
param(
    [Parameter(Mandatory = $true)][string]$ApiKey,
    [int]$NglLayers = 40
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$BINARY     = 'E:\ai\llama-cpp\bin\llama-server.exe'
$MODEL      = 'E:\ai\llama-cpp\models\Qwen3.8-27B\Qwen3.8-27B-Q4_K_M.gguf'
$ALIAS      = 'qwen3.8-27b-q4km'
$PORT       = 8085
$HOST_ADDR  = '127.0.0.1'
$CONTEXT    = 8192
$TIMEOUT_S  = 300

if (-not (Test-Path -LiteralPath $BINARY)) { throw "llama-server.exe not found: $BINARY" }
if (-not (Test-Path -LiteralPath $MODEL))  { throw "Model not found: $MODEL — run Download-Qwen38Model.ps1 first." }
if (Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue) {
    throw "Port $PORT is in use. Stop the occupying process before running the smoke test."
}

$repoRoot   = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$logDir     = Join-Path $repoRoot '.local-ai\logs'
$runtimeDir = Join-Path $repoRoot '.local-ai\runtime'
New-Item -ItemType Directory -Path $logDir     -Force | Out-Null
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

$timestamp  = Get-Date -Format 'yyyyMMddHHmmss'
$stdoutLog  = Join-Path $logDir "qwen38-smoke-$timestamp.stdout.log"
$stderrLog  = Join-Path $logDir "qwen38-smoke-$timestamp.stderr.log"

Write-Host ""
Write-Host "=== Gate I3: Qwen3.8 isolated server smoke ===" -ForegroundColor Cyan
Write-Host "Model  : $MODEL"
Write-Host "Alias  : $ALIAS"
Write-Host "Port   : $PORT"
Write-Host "ngl    : $NglLayers / 64 layers on GPU"
Write-Host "Context: $CONTEXT tokens"
Write-Host ""

$serverArgs = @(
    '-m',    $MODEL,
    '--alias', $ALIAS,
    '--host', $HOST_ADDR,
    '--port', $PORT,
    '--offline',
    '-ngl',  $NglLayers,
    '-c',    $CONTEXT,
    '--parallel', '1',
    '--flash-attn', 'on',
    '--batch-size', '256',
    '--ubatch-size', '256',
    '--threads', '12'
    
)

$env:LLAMA_API_KEY = $ApiKey

# VRAM baseline
$vramBefore = [int]((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -replace '\s','')

Write-Host "Starting server..." -ForegroundColor Gray
$loadStart = [DateTime]::UtcNow
$proc = Start-Process -FilePath $BINARY -ArgumentList $serverArgs `
    -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError  $stderrLog

$deadline = [DateTime]::UtcNow.AddSeconds($TIMEOUT_S)
$healthy  = $false
try {
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($proc.HasExited) {
            $log = Get-Content $stderrLog -Raw -ErrorAction SilentlyContinue
            throw "Server exited during startup.`nLog: $log"
        }
        try {
            $r = Invoke-RestMethod -Uri "http://$HOST_ADDR`:$PORT/health" -TimeoutSec 3 -ErrorAction Stop
            if ($r.status -eq 'ok') { $healthy = $true; break }
        } catch { }
        Start-Sleep -Seconds 3
    }
    if (-not $healthy) { throw "Server did not become healthy within $TIMEOUT_S s." }

    $loadTime  = [math]::Round(([DateTime]::UtcNow - $loadStart).TotalSeconds, 1)
    $vramAfter = [int]((nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -replace '\s','')
    $vramDelta = $vramAfter - $vramBefore

    Write-Host "Load time  : $loadTime s" -ForegroundColor Green
    Write-Host "VRAM delta : $vramDelta MiB  (total: $vramAfter / 12227 MiB)" -ForegroundColor Green

    # Verify alias
    $models = Invoke-RestMethod -Uri "http://$HOST_ADDR`:$PORT/v1/models" `
        -Headers @{ Authorization = "Bearer $ApiKey" } -TimeoutSec 10
    if (-not (@($models.data.id) -contains $ALIAS)) {
        throw "/v1/models did not return alias '$ALIAS'."
    }
    Write-Host "Model alias: $ALIAS verified" -ForegroundColor Green

    # Three sequential completions
    $headers = @{ Authorization = "Bearer $ApiKey"; 'Content-Type' = 'application/json' }
    $results = @()
    for ($i = 1; $i -le 3; $i++) {
        $body = @{
            model    = $ALIAS
            messages = @(@{ role = 'user'; content = "Reply with exactly: call $i ok" })
            max_tokens = 20
            stream   = $false
            chat_template_kwargs = @{ enable_thinking = $false; preserve_thinking = $false }
        } | ConvertTo-Json -Depth 5

        $t0 = [DateTime]::UtcNow
        $resp = Invoke-RestMethod -Uri "http://$HOST_ADDR`:$PORT/v1/chat/completions" `
            -Method Post -Body $body -Headers $headers -TimeoutSec 120
        $latency = [math]::Round(([DateTime]::UtcNow - $t0).TotalMilliseconds)

        $usage    = $resp.usage
        $promptTs = $usage.prompt_tokens
        $genTs    = $usage.completion_tokens
        $content  = $resp.choices[0].message.content
        $reasoning = if ($resp.choices[0].message.PSObject.Properties.Match('reasoning_content').Count -gt 0) {
            [string]$resp.choices[0].message.reasoning_content
        } else {
            ""
        }
        if ([string]::IsNullOrWhiteSpace($content)) { throw "Smoke call $i returned empty content." }
        if (-not [string]::IsNullOrWhiteSpace($reasoning)) { throw "Smoke call $i returned unexpected reasoning content." }

        $results += [ordered]@{
            call           = $i
            latency_ms     = $latency
            prompt_tokens  = $promptTs
            gen_tokens     = $genTs
            response_text  = $content
            reasoning_present = $false
        }
        Write-Host "Call $i : $latency ms | prompt=$promptTs gen=$genTs | '$content'" -ForegroundColor Gray
    }

    # Image-processing latency (plain-text placeholder since we need actual image)
    Write-Host ""
    Write-Host "Note: image-processing latency measured in Gate I4 (vision smoke)." -ForegroundColor Yellow

    # Write results
    $report = [ordered]@{
        schema_version  = 1
        gate            = 'I3'
        timestamp_utc   = ([DateTime]::UtcNow).ToString('o')
        model           = $MODEL
        alias           = $ALIAS
        llama_cpp_build = '10249'
        ngl_layers      = $NglLayers
        context_tokens  = $CONTEXT
        load_time_s     = $loadTime
        vram_before_mib = $vramBefore
        vram_after_mib  = $vramAfter
        vram_delta_mib  = $vramDelta
        vram_total_mib  = 12227
        calls           = $results
        stability       = 'stable_3_sequential'
        stdout_log      = $stdoutLog
        stderr_log      = $stderrLog
    }
    $reportPath = Join-Path $runtimeDir "qwen38-smoke-$timestamp.json"
    $report | ConvertTo-Json -Depth 5 | Set-Content $reportPath -Encoding UTF8
    Write-Host ""
    Write-Host "=== Gate I3 complete ===" -ForegroundColor Green
    Write-Host "Report : $reportPath"
    Write-Host ""
    Write-Host "Review VRAM delta.  If $vramDelta MiB leaves headroom, raise NglLayers." -ForegroundColor Cyan
    Write-Host "Next   : run Test-Qwen38VisionSmoke.ps1 -ApiKey <key>  (Gate I4)" -ForegroundColor Cyan
} finally {
    if ($null -ne $proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
    }
    Remove-Item -Path Env:LLAMA_API_KEY -ErrorAction SilentlyContinue
    Write-Host "Server stopped." -ForegroundColor Gray
}
