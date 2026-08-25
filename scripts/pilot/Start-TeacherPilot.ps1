param(
    [switch]$StartLocalAi,
    # Kept for backwards compatibility with the previous pilot command.  Local
    # models are now on-demand by default, so this switch has the same effect
    # as omitting -StartLocalAi.
    [switch]$SkipLocalAi,
    [switch]$RebuildFrontend,
    [ValidateSet("Qwen", "Qwen38")]
    [string]$LocalAiMode = "Qwen38",
    [int]$HealthTimeoutSeconds = 600
)

. (Join-Path $PSScriptRoot "Common.ps1")

$paths = Get-PilotPaths
Assert-PilotRuntime -Paths $paths
Import-PilotEnvironment -Paths $paths

function Get-NewestSourceWriteTimeUtc {
    param([Parameter(Mandatory = $true)][string[]]$SourcePaths)

    $newest = [DateTime]::MinValue
    foreach ($sourcePath in $SourcePaths) {
        if (-not (Test-Path -LiteralPath $sourcePath)) {
            continue
        }
        $item = Get-Item -LiteralPath $sourcePath
        if (-not $item.PSIsContainer) {
            if ($item.LastWriteTimeUtc -gt $newest) {
                $newest = $item.LastWriteTimeUtc
            }
            continue
        }
        $newestChild = Get-ChildItem -LiteralPath $sourcePath -Recurse -File |
            Where-Object {
                $_.Extension -in @(".py", ".ini", ".toml") -and
                $_.FullName -notmatch "[\\/]__pycache__[\\/]"
            } |
            Sort-Object LastWriteTimeUtc -Descending |
            Select-Object -First 1
        if ($null -ne $newestChild -and $newestChild.LastWriteTimeUtc -gt $newest) {
            $newest = $newestChild.LastWriteTimeUtc
        }
    }
    return $newest
}

if ($StartLocalAi -and $SkipLocalAi) {
    throw "Use either -StartLocalAi or -SkipLocalAi, not both."
}

$psql = Join-Path $paths.PostgresBin "psql.exe"
$postgresExe = Join-Path $paths.PostgresBin "postgres.exe"
$pgReady = $false
try {
    $pgReady = (& $psql -h 127.0.0.1 -U postgres -d postgres -Atc "SELECT 1" 2>&1) -eq "1"
} catch {
    $pgReady = $false
}
if (-not $pgReady) {
    if (Test-PilotPort -Port 5432) {
        throw "Port 5432 is already occupied by an unrecognized PostgreSQL instance."
    }
    $pgProcess = Start-PilotProcess -Paths $paths -Name "postgres" `
        -Executable $postgresExe -Arguments @("-D", $paths.PostgresData) `
        -WorkingDirectory $paths.RepositoryRoot
    $deadline = [DateTime]::UtcNow.AddSeconds(15)
    while ([DateTime]::UtcNow -lt $deadline -and -not $pgReady) {
        try {
            $pgReady = (& $psql -h 127.0.0.1 -U postgres -d postgres -Atc "SELECT 1" 2>&1) -eq "1"
        } catch {
            $pgReady = $false
        }
        if ($pgReady) { break }
        Start-Sleep -Milliseconds 200
    }
    if (-not $pgReady) {
        throw "PostgreSQL failed to start."
    }
} else {
    Write-Host "PostgreSQL is already running."
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

# Local models stay off during ordinary pilot startup; an operator may
# explicitly select one managed phase with -StartLocalAi.
if ($StartLocalAi) {
    . (Join-Path $paths.RepositoryRoot "scripts\local-ai\Common.ps1")
    # Always use the phase switch, even when the requested server is already
    # healthy: it first stops the other repository-owned phase, which is the
    # only way to preserve the one-model VRAM invariant after an interrupted
    # host session or a manual operator action.
    & (Join-Path $paths.RepositoryRoot "scripts\local-ai\Switch-LocalAiPhase.ps1") `
        -HealthTimeoutSeconds $HealthTimeoutSeconds -Phase $LocalAiMode
} else {
    # "On demand" must mean no phase is resident, not merely that this
    # invocation declined to launch one.  Stop repository-owned phases and
    # fail closed when a listener on a reserved phase port has unknown
    # ownership; leaving it running would make later teacher actions appear to
    # have loaded a model when they did not.
    $stopScript = Join-Path $paths.RepositoryRoot "scripts\local-ai\Stop-LocalAi.ps1"
    foreach ($mode in @("PaddleOcr", "Qwen", "Qwen38")) {
        try {
            & $stopScript -ConfigPath (Join-Path $paths.RepositoryRoot ".env.local-ai") -Mode $mode
        } catch {
            throw "Local AI phase $mode could not be verified stopped; refusing ordinary pilot startup."
        }
    }
    Write-Host "Local AI is on demand and all managed phases are stopped."
}

$backendSourceTimestamp = Get-NewestSourceWriteTimeUtc -SourcePaths @(
    (Join-Path $paths.ApiDirectory "app"),
    (Join-Path $paths.ApiDirectory "packages"),
    (Join-Path $paths.ApiDirectory "alembic"),
    (Join-Path $paths.ApiDirectory "alembic.ini"),
    (Join-Path $paths.RepositoryRoot ".env.local-ai")
)
$existingApi = Get-PilotOwnedProcess -Paths $paths -Name "api" `
    -ExpectedExecutable $paths.ApiPython
$existingWorker = Get-PilotOwnedProcess -Paths $paths -Name "worker" `
    -ExpectedExecutable $paths.ApiPython
$backendRuntimeStale = (
    $null -ne $existingApi -and
    $backendSourceTimestamp -gt $existingApi.StartTime.ToUniversalTime()
) -or (
    $null -ne $existingWorker -and
    $backendSourceTimestamp -gt $existingWorker.StartTime.ToUniversalTime()
)
if ($backendRuntimeStale) {
    if ($null -ne $existingWorker) {
        Stop-PilotProcess -Paths $paths -Name "worker" -ExpectedExecutable $paths.ApiPython
    }
    if ($null -ne $existingApi) {
        Stop-PilotProcess -Paths $paths -Name "api" -ExpectedExecutable $paths.ApiPython
    }
    Write-Host "Backend source or local configuration changed; API and worker will restart."
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
$frontendBuildStale = -not (Test-Path -LiteralPath $buildId -PathType Leaf)
if (-not $frontendBuildStale) {
    $buildTimestamp = (Get-Item -LiteralPath $buildId).LastWriteTimeUtc
    $frontendSourcePaths = @(
        (Join-Path $paths.WebDirectory "app"),
        (Join-Path $paths.WebDirectory "components"),
        (Join-Path $paths.WebDirectory "e2e"),
        (Join-Path $paths.WebDirectory "lib"),
        (Join-Path $paths.WebDirectory "next.config.ts"),
        (Join-Path $paths.WebDirectory "package.json"),
        (Join-Path $paths.WebDirectory "package-lock.json"),
        (Join-Path $paths.WebDirectory "tsconfig.json")
    )
    foreach ($sourcePath in $frontendSourcePaths) {
        if (-not (Test-Path -LiteralPath $sourcePath)) {
            continue
        }
        $sourceItem = Get-Item -LiteralPath $sourcePath
        if (-not $sourceItem.PSIsContainer -and $sourceItem.LastWriteTimeUtc -gt $buildTimestamp) {
            $frontendBuildStale = $true
            break
        }
        if ($sourceItem.PSIsContainer) {
            $newerSource = Get-ChildItem -LiteralPath $sourcePath -Recurse -File | Where-Object {
                $_.LastWriteTimeUtc -gt $buildTimestamp
            } | Select-Object -First 1
            if ($null -ne $newerSource) {
                $frontendBuildStale = $true
                break
            }
        }
    }
}
$frontendNeedsBuild = $RebuildFrontend -or $frontendBuildStale
$existingFrontend = Get-PilotOwnedProcess -Paths $paths -Name "frontend" `
    -ExpectedExecutable $paths.Node
if ($frontendNeedsBuild -and $null -ne $existingFrontend) {
    # Never replace .next beneath a running Next server. Doing so can leave the
    # browser requesting chunks from a different build until a manual restart.
    Stop-PilotProcess -Paths $paths -Name "frontend" -ExpectedExecutable $paths.Node
    $existingFrontend = $null
}
if ($frontendNeedsBuild) {
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
$buildIdTimestamp = (Get-Item -LiteralPath $buildId).LastWriteTimeUtc
if (
    $null -ne $existingFrontend -and
    $buildIdTimestamp -gt $existingFrontend.StartTime.ToUniversalTime()
) {
    Stop-PilotProcess -Paths $paths -Name "frontend" -ExpectedExecutable $paths.Node
    Write-Host "Frontend build changed; the Next server will restart."
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
if ($StartLocalAi) {
    Write-Host "Local AI startup phase: $LocalAiMode"
} else {
    Write-Host "Local AI startup phase: on demand (not started)"
}
Write-Host "Cohort model grading enabled: $env:COHORT_MODEL_GRADING_ENABLED"
if ($env:COHORT_MODEL_GRADING_ENABLED -ne "true") {
    Write-Host "Real cohort grading remains safety-locked until the curated evaluation reports PASS."
}
