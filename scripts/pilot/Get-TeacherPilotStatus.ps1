param([switch]$RequireAll)

. (Join-Path $PSScriptRoot "Common.ps1")
. (Join-Path $PSScriptRoot "..\local-ai\Common.ps1")

$paths = Get-PilotPaths
Assert-PilotRuntime -Paths $paths
Import-PilotEnvironment -Paths $paths
$localAiEnv = Join-Path $paths.RepositoryRoot ".env.local-ai"
if (Test-Path -LiteralPath $localAiEnv) {
    Import-LocalAiEnvironment -Path $localAiEnv
}

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

$psql = Join-Path $paths.PostgresBin "psql.exe"
$postgresReady = $false
try {
    $postgresReady = (& $psql -h 127.0.0.1 -U postgres -d postgres -Atc "SELECT 1" 2>&1) -eq "1"
} catch {
    $postgresReady = $false
}
$redisReady = $false
try {
    $redisReady = (& $paths.RedisCli -h 127.0.0.1 -p 6379 PING 2>$null) -eq "PONG"
} catch {
    $redisReady = $false
}
$localAiRuntimeDirectory = Join-Path $paths.RepositoryRoot ".local-ai"
$qwen38Runtime = Get-LocalAiRuntimeState -Port 8085 `
    -ExpectedExecutable $env:LOCAL_QWEN38_BINARY_PATH `
    -PidPath (Join-Path $localAiRuntimeDirectory "qwen38.pid")

$qwen38Ready = $false
try {
    $models = Invoke-RestMethod -Uri "http://127.0.0.1:8085/v1/models" `
        -Headers @{ Authorization = "Bearer $env:LOCAL_QWEN38_API_KEY" } -TimeoutSec 5
    $qwen38Ready = $qwen38Runtime.Safe `
        -and (@($models.data.id) -contains $env:LOCAL_QWEN38_MODEL)
} catch {
    $qwen38Ready = $false
}
$workerReady = $null -ne (Get-PilotOwnedProcess -Paths $paths -Name "worker" -ExpectedExecutable $paths.ApiPython)

$status = @(
    [pscustomobject]@{ Service = "PostgreSQL"; Ready = $postgresReady; State = "managed"; Endpoint = "127.0.0.1:5432" },
    [pscustomobject]@{ Service = "Redis/RQ"; Ready = $redisReady; State = "managed"; Endpoint = "127.0.0.1:6379" },
    [pscustomobject]@{ Service = "Backend"; Ready = (Test-HttpEndpoint "http://127.0.0.1:8000/health"); State = "managed"; Endpoint = "http://localhost:8000" },
    [pscustomobject]@{ Service = "RQ worker"; Ready = $workerReady; State = "managed"; Endpoint = "teacher-assistant-default" },
    [pscustomobject]@{ Service = "Frontend"; Ready = (Test-HttpEndpoint "http://127.0.0.1:3000"); State = "managed"; Endpoint = "http://localhost:3000" },
    [pscustomobject]@{ Service = "Local Qwen3.8"; Ready = $qwen38Ready; State = $qwen38Runtime.Label; Endpoint = "127.0.0.1:8085" }
)
$status | Format-Table -AutoSize
Write-Host "Cohort model grading enabled: $env:COHORT_MODEL_GRADING_ENABLED"
$coreReady = $postgresReady -and $redisReady -and $workerReady `
    -and (Test-HttpEndpoint "http://127.0.0.1:8000/health") `
    -and (Test-HttpEndpoint "http://127.0.0.1:3000")
$localPhaseReady = $qwen38Ready
$unsafeLocalAi = -not $qwen38Runtime.Safe
if ($unsafeLocalAi) {
    Write-Warning "An unsafe or unmanaged local AI listener was detected."
    exit 1
}
if ($RequireAll -and (-not $coreReady -or -not $localPhaseReady)) {
    exit 1
}
