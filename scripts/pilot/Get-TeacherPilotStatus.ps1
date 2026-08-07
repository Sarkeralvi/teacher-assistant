param([switch]$RequireAll)

. (Join-Path $PSScriptRoot "Common.ps1")

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

$pgCtl = Join-Path $paths.PostgresBin "pg_ctl.exe"
& $pgCtl status -D $paths.PostgresData *> $null
$postgresReady = $LASTEXITCODE -eq 0
$redisReady = $false
try {
    $redisReady = (& $paths.RedisCli -h 127.0.0.1 -p 6379 PING 2>$null) -eq "PONG"
} catch {
    $redisReady = $false
}
$qwenReady = $false
try {
    $models = Invoke-RestMethod -Uri "http://127.0.0.1:8080/v1/models" `
        -Headers @{ Authorization = "Bearer $env:LOCAL_QWEN_API_KEY" } -TimeoutSec 5
    $qwenReady = @($models.data.id) -contains $env:LOCAL_QWEN_MODEL
} catch {
    $qwenReady = $false
}
$ocrReady = $false
try {
    $ocrHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8090/health" `
        -Headers @{ Authorization = "Bearer $env:LOCAL_OCR_API_KEY" } -TimeoutSec 5
    $ocrReady = $ocrHealth.status -eq "ready" -and $ocrHealth.device -eq "cpu"
} catch {
    $ocrReady = $false
}
$workerReady = $null -ne (Get-PilotOwnedProcess -Paths $paths -Name "worker" -ExpectedExecutable $paths.ApiPython)

$status = @(
    [pscustomobject]@{ Service = "PostgreSQL"; Ready = $postgresReady; Endpoint = "127.0.0.1:5432" },
    [pscustomobject]@{ Service = "Redis/RQ"; Ready = $redisReady; Endpoint = "127.0.0.1:6379" },
    [pscustomobject]@{ Service = "Backend"; Ready = (Test-HttpEndpoint "http://127.0.0.1:8000/health"); Endpoint = "http://localhost:8000" },
    [pscustomobject]@{ Service = "RQ worker"; Ready = $workerReady; Endpoint = "teacher-assistant-default" },
    [pscustomobject]@{ Service = "Frontend"; Ready = (Test-HttpEndpoint "http://127.0.0.1:3000"); Endpoint = "http://localhost:3000" },
    [pscustomobject]@{ Service = "Local Qwen"; Ready = $qwenReady; Endpoint = "127.0.0.1:8080" },
    [pscustomobject]@{ Service = "PaddleOCR CPU"; Ready = $ocrReady; Endpoint = "127.0.0.1:8090" }
)
$status | Format-Table -AutoSize
Write-Host "Cohort model grading enabled: $env:COHORT_MODEL_GRADING_ENABLED"
if ($RequireAll -and $status.Ready -contains $false) {
    exit 1
}
