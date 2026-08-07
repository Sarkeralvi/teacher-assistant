param(
    [string]$ConfigPath,
    [int]$HealthTimeoutSeconds = 240
)

. (Join-Path $PSScriptRoot "Common.ps1")

$repositoryRoot = Get-RepositoryRoot
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repositoryRoot ".env.local-ai"
}
& (Join-Path $PSScriptRoot "Test-LocalAiPreflight.ps1") -ConfigPath $ConfigPath
Import-LocalAiEnvironment -Path $ConfigPath

$qwenBinary = Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN_BINARY_PATH"
$qwenModel = Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN_MODEL_PATH"
$ocrPython = Assert-RequiredEnvironmentValue -Name "LOCAL_OCR_PYTHON_PATH"
$qwenKey = Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN_API_KEY"
$ocrKey = Assert-RequiredEnvironmentValue -Name "LOCAL_OCR_API_KEY"

$runtimeDirectory = Join-Path $repositoryRoot ".local-ai"
$logDirectory = Join-Path $runtimeDirectory "logs"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

$qwenArguments = @(
    "-m", ('"' + $qwenModel + '"'),
    "--alias", "qwen3.6-35b-a3b-q4km",
    "--host", "127.0.0.1",
    "--port", "8080",
    "--offline",
    "--jinja",
    "--reasoning", "off",
    "--reasoning-format", "deepseek",
    "-ngl", "99",
    "--n-cpu-moe", "20",
    "-c", "32768",
    "--parallel", "1",
    "--no-mmap",
    "--flash-attn", "on",
    "--cache-type-k", "q8_0",
    "--cache-type-v", "q8_0",
    "--threads", "12",
    "--batch-size", "512"
)
$env:LLAMA_API_KEY = $qwenKey
$qwenProcess = $null
$ocrProcess = $null
try {
    $qwenProcess = Start-Process -FilePath $qwenBinary -ArgumentList $qwenArguments `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDirectory "qwen.stdout.log") `
        -RedirectStandardError (Join-Path $logDirectory "qwen.stderr.log")

    $ocrProcess = Start-Process -FilePath $ocrPython `
        -ArgumentList @("-m", "packages.local_ocr_sidecar.server") `
        -WorkingDirectory (Join-Path $repositoryRoot "apps\api") `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDirectory "ocr.stdout.log") `
        -RedirectStandardError (Join-Path $logDirectory "ocr.stderr.log")

    [IO.File]::WriteAllText((Join-Path $runtimeDirectory "qwen.pid"), [string]$qwenProcess.Id)
    [IO.File]::WriteAllText((Join-Path $runtimeDirectory "ocr.pid"), [string]$ocrProcess.Id)

    $deadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSeconds)
    $qwenReady = $false
    $ocrReady = $false
    while ([DateTime]::UtcNow -lt $deadline -and (-not $qwenReady -or -not $ocrReady)) {
        if ($qwenProcess.HasExited -or $ocrProcess.HasExited) {
            throw "A local AI service exited during startup. Inspect .local-ai/logs."
        }
        if (-not $qwenReady) {
            try {
                $models = Invoke-RestMethod -Uri "http://127.0.0.1:8080/v1/models" `
                    -Headers @{ Authorization = "Bearer $qwenKey" } -TimeoutSec 3
                $qwenReady = @($models.data.id) -contains "qwen3.6-35b-a3b-q4km"
            } catch {
                $qwenReady = $false
            }
        }
        if (-not $ocrReady) {
            try {
                $health = Invoke-RestMethod -Uri "http://127.0.0.1:8090/health" `
                    -Headers @{ Authorization = "Bearer $ocrKey" } -TimeoutSec 3
                $ocrReady = $health.status -eq "ready"
            } catch {
                $ocrReady = $false
            }
        }
        if (-not $qwenReady -or -not $ocrReady) {
            Start-Sleep -Seconds 2
        }
    }

    if (-not $qwenReady -or -not $ocrReady) {
        throw "Local AI services did not become healthy. Inspect .local-ai/logs."
    }
    Write-Host "Local AI services are healthy on loopback."
    Write-Host "Qwen PID: $($qwenProcess.Id); OCR PID: $($ocrProcess.Id)"
} catch {
    foreach ($process in @($qwenProcess, $ocrProcess)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item -LiteralPath (Join-Path $runtimeDirectory "qwen.pid") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $runtimeDirectory "ocr.pid") -Force -ErrorAction SilentlyContinue
    throw
}
