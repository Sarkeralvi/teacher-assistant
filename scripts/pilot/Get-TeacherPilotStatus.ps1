param([switch]$RequireAll)

. (Join-Path $PSScriptRoot "Common.ps1")
. (Join-Path $PSScriptRoot "..\local-ai\Common.ps1")

$paths = Get-PilotPaths
Assert-PilotRuntime -Paths $paths
Import-PilotEnvironment -Paths $paths

function Test-HttpEndpoint {
    param([string]$Uri, [hashtable]$Headers = @{})
    try {
        $response = Invoke-WebRequest -Uri $Uri -Headers $Headers -UseBasicParsing -TimeoutSec 5
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
    } catch {
        return $false
    }
}

function Get-LocalAiRuntimeState {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable,
        [Parameter(Mandatory = $true)][string]$PidPath
    )

    $listeners = @(Get-LocalAiListenerInfo -Port $Port)
    if ($listeners.Count -eq 0) {
        return [pscustomobject]@{
            Running = $false
            Safe = $true
            Managed = $false
            Label = "off"
        }
    }

    $recordedProcessId = 0
    $hasValidPid = $false
    if (Test-Path -LiteralPath $PidPath -PathType Leaf) {
        $rawProcessId = (Get-Content -LiteralPath $PidPath -Raw).Trim()
        $hasValidPid = [int]::TryParse($rawProcessId, [ref]$recordedProcessId) `
            -and $recordedProcessId -gt 0
    }
    $loopbackOnly = @($listeners | Where-Object { -not $_.IsLoopback }).Count -eq 0
    $expectedExecutableOnly = @(
        $listeners | Where-Object {
            -not (Test-LocalAiExecutablePath `
                -ActualPath $_.ExecutablePath `
                -ExpectedPath $ExpectedExecutable)
        }
    ).Count -eq 0
    $managed = $hasValidPid -and @(
        $listeners | Where-Object { $_.ProcessId -ne $recordedProcessId }
    ).Count -eq 0
    $safe = $loopbackOnly -and $expectedExecutableOnly -and $managed
    $label = if (-not $loopbackOnly) {
        "UNSAFE non-loopback"
    } elseif (-not $expectedExecutableOnly) {
        "UNSAFE unexpected process"
    } elseif (-not $managed) {
        "UNSAFE unmanaged"
    } else {
        "loopback/managed"
    }
    return [pscustomobject]@{
        Running = $true
        Safe = $safe
        Managed = $managed
        Label = $label
    }
}

$pgCtl = Join-Path $paths.PostgresBin "pg_ctl.exe"
& $pgCtl status -D $paths.PostgresData *> $null
$postgresReady = $LASTEXITCODE -eq 0
$redisReady = $false
try {
    $redisReady = (& $paths.RedisCli -h 127.0.0.1 -p 6379 PING 2>$null) -eq "PONG"
} catch {
    $redisReady = $false
}
$localAiRuntimeDirectory = Join-Path $paths.RepositoryRoot ".local-ai"
$qwenRuntime = Get-LocalAiRuntimeState -Port 8080 `
    -ExpectedExecutable $env:LOCAL_QWEN_BINARY_PATH `
    -PidPath (Join-Path $localAiRuntimeDirectory "qwen.pid")
$ocrRuntime = Get-LocalAiRuntimeState -Port 8090 `
    -ExpectedExecutable $env:LOCAL_OCR_PYTHON_PATH `
    -PidPath (Join-Path $localAiRuntimeDirectory "ocr.pid")

$qwenReady = $false
try {
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:8080/props" `
        -Headers @{ Authorization = "Bearer $env:LOCAL_QWEN_API_KEY" } -TimeoutSec 5
    $models = Invoke-RestMethod -Uri "http://127.0.0.1:8080/v1/models" `
        -Headers @{ Authorization = "Bearer $env:LOCAL_QWEN_API_KEY" } -TimeoutSec 5
    $qwenReady = $qwenRuntime.Safe `
        -and (@($models.data.id) -contains $env:LOCAL_QWEN_MODEL)
} catch {
    $qwenReady = $false
}
$ocrReady = $false
$ocrDevice = "not running"
try {
    $ocrHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8090/health" `
        -Headers @{ Authorization = "Bearer $env:LOCAL_OCR_API_KEY" } -TimeoutSec 5
    $ocrReady = $ocrRuntime.Safe `
        -and $ocrHealth.status -eq "ready" `
        -and $ocrHealth.device -in @("cpu", "gpu:0")
    if ($ocrReady) {
        $ocrDevice = [string]$ocrHealth.device
    }
} catch {
    $ocrReady = $false
}
$workerReady = $null -ne (Get-PilotOwnedProcess -Paths $paths -Name "worker" -ExpectedExecutable $paths.ApiPython)

$status = @(
    [pscustomobject]@{ Service = "PostgreSQL"; Ready = $postgresReady; State = "managed"; Endpoint = "127.0.0.1:5432" },
    [pscustomobject]@{ Service = "Redis/RQ"; Ready = $redisReady; State = "managed"; Endpoint = "127.0.0.1:6379" },
    [pscustomobject]@{ Service = "Backend"; Ready = (Test-HttpEndpoint "http://127.0.0.1:8000/health"); State = "managed"; Endpoint = "http://localhost:8000" },
    [pscustomobject]@{ Service = "RQ worker"; Ready = $workerReady; State = "managed"; Endpoint = "teacher-assistant-default" },
    [pscustomobject]@{ Service = "Frontend"; Ready = (Test-HttpEndpoint "http://127.0.0.1:3000"); State = "managed"; Endpoint = "http://localhost:3000" },
    [pscustomobject]@{ Service = "Local Qwen"; Ready = $qwenReady; State = $qwenRuntime.Label; Endpoint = "127.0.0.1:8080" },
    [pscustomobject]@{ Service = "PaddleOCR ($ocrDevice)"; Ready = $ocrReady; State = $ocrRuntime.Label; Endpoint = "127.0.0.1:8090" }
)
$status | Format-Table -AutoSize
Write-Host "Cohort model grading enabled: $env:COHORT_MODEL_GRADING_ENABLED"
$coreReady = $postgresReady -and $redisReady -and $workerReady `
    -and (Test-HttpEndpoint "http://127.0.0.1:8000/health") `
    -and (Test-HttpEndpoint "http://127.0.0.1:3000")
$localPhaseReady = $qwenReady -or $ocrReady
$unsafeLocalAi = -not $qwenRuntime.Safe -or -not $ocrRuntime.Safe
if ($unsafeLocalAi) {
    Write-Warning "An unsafe or unmanaged local AI listener was detected."
    exit 1
}
if ($RequireAll -and (-not $coreReady -or -not $localPhaseReady)) {
    exit 1
}
