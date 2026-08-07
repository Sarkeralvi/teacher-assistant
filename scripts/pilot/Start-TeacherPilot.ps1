param(
    [switch]$SkipLocalAi,
    [switch]$RebuildFrontend,
    [ValidateSet("Concurrent", "OcrGpu", "OcrCpu", "Qwen")]
    [string]$LocalAiMode = "Qwen",
    [int]$HealthTimeoutSeconds = 600
)

. (Join-Path $PSScriptRoot "Common.ps1")

$paths = Get-PilotPaths
Assert-PilotRuntime -Paths $paths
Import-PilotEnvironment -Paths $paths

$pgCtl = Join-Path $paths.PostgresBin "pg_ctl.exe"
$pgStatusOutput = & $pgCtl status -D $paths.PostgresData 2>&1
if ($LASTEXITCODE -ne 0) {
    if (Test-PilotPort -Port 5432) {
        throw "Port 5432 is already occupied by an unrecognized PostgreSQL instance."
    }
    & $pgCtl start -D $paths.PostgresData `
        -l (Join-Path $paths.LogRoot "postgres.log") -w
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL failed to start."
    }
} else {
    Write-Host ($pgStatusOutput | Select-Object -First 1)
}

$psql = Join-Path $paths.PostgresBin "psql.exe"
$createdb = Join-Path $paths.PostgresBin "createdb.exe"
$roleExists = & $psql -h 127.0.0.1 -U postgres -d postgres -Atc `
    "SELECT 1 FROM pg_roles WHERE rolname='teacher_assistant'"
if (-not $roleExists) {
    & $psql -h 127.0.0.1 -U postgres -d postgres -v ON_ERROR_STOP=1 `
        -c "CREATE ROLE teacher_assistant LOGIN PASSWORD 'teacher_assistant_dev_password'" | Out-Null
}
$databaseExists = & $psql -h 127.0.0.1 -U postgres -d postgres -Atc `
    "SELECT 1 FROM pg_database WHERE datname='teacher_assistant'"
if (-not $databaseExists) {
    & $createdb -h 127.0.0.1 -U postgres -O teacher_assistant teacher_assistant
}

$redisReady = $false
try {
    $redisReady = (& $paths.RedisCli -h 127.0.0.1 -p 6379 PING 2>$null) -eq "PONG"
} catch {
    $redisReady = $false
}
if (-not $redisReady) {
    if (Test-PilotPort -Port 6379) {
        throw "Port 6379 is occupied by an unrecognized process."
    }
    $redisProcess = Start-PilotProcess -Paths $paths -Name "redis" `
        -Executable $paths.RedisServer -Arguments @($paths.RedisConfig) `
        -WorkingDirectory $paths.RedisData
    Start-Sleep -Seconds 2
    if ($redisProcess.HasExited -or (& $paths.RedisCli -h 127.0.0.1 -p 6379 PING) -ne "PONG") {
        throw "Redis-compatible service failed to start."
    }
}

Push-Location $paths.ApiDirectory
try {
    & $paths.ApiPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic migration failed."
    }
} finally {
    Pop-Location
}

if (-not $SkipLocalAi) {
    $qwenReady = $false
    $ocrReady = $false
    try {
        $models = Invoke-RestMethod -Uri "http://127.0.0.1:8080/v1/models" `
            -Headers @{ Authorization = "Bearer $env:LOCAL_QWEN_API_KEY" } -TimeoutSec 3
        $qwenReady = @($models.data.id) -contains $env:LOCAL_QWEN_MODEL
    } catch {
        $qwenReady = $false
    }
    try {
        $ocrHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8090/health" `
            -Headers @{ Authorization = "Bearer $env:LOCAL_OCR_API_KEY" } -TimeoutSec 3
        $ocrReady = $ocrHealth.status -eq "ready"
    } catch {
        $ocrReady = $false
    }
    $desiredReady = switch ($LocalAiMode) {
        "Concurrent" { $qwenReady -and $ocrReady }
        "Qwen" { $qwenReady -and -not $ocrReady }
        { $_ -in @("OcrGpu", "OcrCpu") } { $ocrReady -and -not $qwenReady }
    }
    if (-not $desiredReady) {
        & (Join-Path $paths.RepositoryRoot "scripts\local-ai\Stop-LocalAi.ps1")
        & (Join-Path $paths.RepositoryRoot "scripts\local-ai\Start-LocalAi.ps1") `
            -HealthTimeoutSeconds $HealthTimeoutSeconds -Mode $LocalAiMode
    } else {
        Write-Host "Local AI phase '$LocalAiMode' is already healthy."
    }
}

$apiProcess = Start-PilotProcess -Paths $paths -Name "api" `
    -Executable $paths.ApiPython `
    -Arguments @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000") `
    -WorkingDirectory $paths.ApiDirectory
Wait-PilotHttp -Uri "http://127.0.0.1:8000/health" -TimeoutSeconds 60
if ($apiProcess.HasExited) {
    throw "Backend exited during startup."
}

$existingWorker = Get-PilotOwnedProcess -Paths $paths -Name "worker" `
    -ExpectedExecutable $paths.ApiPython
if ($null -eq $existingWorker) {
    # An interrupted Windows host session can leave the RQ worker registration
    # in Redis after its process has gone. Remove only this pilot's fixed worker
    # name before launching its replacement.
    Push-Location $paths.ApiDirectory
    try {
        & $paths.ApiPython -c `
            "from app.redis_client import get_redis_client; from rq import Worker; c=get_redis_client(); [w.register_death() for w in Worker.all(connection=c) if w.name == 'teacher-assistant-windows-pilot']"
        if ($LASTEXITCODE -ne 0) {
            throw "Stale RQ worker cleanup failed."
        }
    } finally {
        Pop-Location
    }
}

$workerProcess = Start-PilotProcess -Paths $paths -Name "worker" `
    -Executable $paths.ApiPython -Arguments @("-m", "app.worker.run") `
    -WorkingDirectory $paths.ApiDirectory
Start-Sleep -Seconds 2
if ($workerProcess.HasExited) {
    throw "RQ worker exited during startup. Inspect .local-ai/logs/worker.stderr.log."
}

$buildId = Join-Path $paths.WebDirectory ".next\BUILD_ID"
if ($RebuildFrontend -or -not (Test-Path -LiteralPath $buildId -PathType Leaf)) {
    Push-Location $paths.WebDirectory
    try {
        & $paths.Npm run build
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend build failed."
        }
    } finally {
        Pop-Location
    }
}
$nextEntry = Join-Path $paths.WebDirectory "node_modules\next\dist\bin\next"
$frontendProcess = Start-PilotProcess -Paths $paths -Name "frontend" `
    -Executable $paths.Node `
    -Arguments @($nextEntry, "start", "--hostname", "127.0.0.1", "--port", "3000") `
    -WorkingDirectory $paths.WebDirectory
Wait-PilotHttp -Uri "http://127.0.0.1:3000" -TimeoutSeconds 60
if ($frontendProcess.HasExited) {
    throw "Frontend exited during startup."
}

Write-Host "Teacher Assistant host environment is healthy."
Write-Host "Frontend: http://localhost:3000"
Write-Host "Backend:  http://localhost:8000/health"
Write-Host "Local AI startup phase: $LocalAiMode"
Write-Host "Cohort model grading enabled: $env:COHORT_MODEL_GRADING_ENABLED"
if ($env:COHORT_MODEL_GRADING_ENABLED -ne "true") {
    Write-Host "Real cohort grading remains safety-locked until the curated evaluation reports PASS."
}
