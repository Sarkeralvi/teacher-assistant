param(
    [switch]$RequireCore,
    [switch]$RequireAll
)

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
function Get-ManagedLocalAiPhaseStatus {
    param([Parameter(Mandatory = $true)][ValidateSet("Qwen", "Qwen38")][string]$Mode)

    $definition = Get-LocalAiServiceDefinition -Mode $Mode
    $runtimeDirectory = Join-Path $paths.RepositoryRoot ".local-ai"
    $binary = [Environment]::GetEnvironmentVariable($definition.BinaryVariable)
    $key = [Environment]::GetEnvironmentVariable($definition.KeyVariable)
    if ([string]::IsNullOrWhiteSpace($binary)) {
        $listeners = @(Get-LocalAiListenerInfo -Port $definition.Port)
        $runtime = if ($listeners.Count -eq 0) {
            [pscustomobject]@{ Running = $false; Safe = $true; Managed = $false; Label = "off" }
        } else {
            [pscustomobject]@{ Running = $true; Safe = $false; Managed = $false; Label = "UNSAFE missing config" }
        }
        return [pscustomobject]@{ Definition = $definition; Runtime = $runtime; Ready = $false }
    }

    $runtime = Get-LocalAiRuntimeState -Port $definition.Port `
        -ExpectedExecutable $binary `
        -PidPath (Join-Path $runtimeDirectory $definition.PidFileName)
    $ready = $false
    if ($runtime.Running -and $runtime.Safe -and -not [string]::IsNullOrWhiteSpace($key)) {
        try {
            $models = Invoke-RestMethod -Uri "http://127.0.0.1:$($definition.Port)/v1/models" `
                -Headers @{ Authorization = "Bearer $key" } -TimeoutSec 5
            $ready = @($models.data.id) -contains $definition.Alias
        } catch {
            $ready = $false
        }
    }
    return [pscustomobject]@{ Definition = $definition; Runtime = $runtime; Ready = $ready }
}

$qwenRuntime = Get-ManagedLocalAiPhaseStatus -Mode Qwen
$qwen38Runtime = Get-ManagedLocalAiPhaseStatus -Mode Qwen38
$workerReady = $null -ne (Get-PilotOwnedProcess -Paths $paths -Name "worker" -ExpectedExecutable $paths.ApiPython)

$status = @(
    [pscustomobject]@{ Service = "PostgreSQL"; Ready = $postgresReady; State = "managed"; Endpoint = "127.0.0.1:5432" },
    [pscustomobject]@{ Service = "Redis/RQ"; Ready = $redisReady; State = "managed"; Endpoint = "127.0.0.1:6379" },
    [pscustomobject]@{ Service = "Backend"; Ready = (Test-HttpEndpoint "http://127.0.0.1:8000/health"); State = "managed"; Endpoint = "http://localhost:8000" },
    [pscustomobject]@{ Service = "RQ worker"; Ready = $workerReady; State = "managed"; Endpoint = "teacher-assistant-default" },
    [pscustomobject]@{ Service = "Frontend"; Ready = (Test-HttpEndpoint "http://127.0.0.1:3000"); State = "managed"; Endpoint = "http://localhost:3000" },
    [pscustomobject]@{ Service = "Local Qwen3.6"; Ready = $qwenRuntime.Ready; State = $qwenRuntime.Runtime.Label; Endpoint = "127.0.0.1:$($qwenRuntime.Definition.Port)" },
    [pscustomobject]@{ Service = "Local Qwen3.8"; Ready = $qwen38Runtime.Ready; State = $qwen38Runtime.Runtime.Label; Endpoint = "127.0.0.1:$($qwen38Runtime.Definition.Port)" }
)
$status | Format-Table -AutoSize
Write-Host "Cohort model grading enabled: $env:COHORT_MODEL_GRADING_ENABLED"
$coreReady = $postgresReady -and $redisReady -and $workerReady `
    -and (Test-HttpEndpoint "http://127.0.0.1:8000/health") `
    -and (Test-HttpEndpoint "http://127.0.0.1:3000")
$localPhaseReady = $qwenRuntime.Ready -or $qwen38Runtime.Ready
$unsafeLocalAi = -not $qwenRuntime.Runtime.Safe -or -not $qwen38Runtime.Runtime.Safe
if ($unsafeLocalAi) {
    Write-Warning "An unsafe or unmanaged local AI listener was detected."
    exit 1
}
if (($RequireCore -and -not $coreReady) -or
    ($RequireAll -and (-not $coreReady -or -not $localPhaseReady))) {
    exit 1
}
