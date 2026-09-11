param([switch]$KeepLocalAi)

. (Join-Path $PSScriptRoot "Common.ps1")

$paths = Get-PilotPaths
Assert-PilotRuntime -Paths $paths
Import-PilotEnvironment -Paths $paths

Stop-PilotProcess -Paths $paths -Name "frontend" -ExpectedExecutable $paths.Node

$workerProcess = Get-PilotOwnedProcess -Paths $paths -Name "worker" -ExpectedExecutable $paths.ApiPython
if ($null -ne $workerProcess) {
    Push-Location $paths.ApiDirectory
    try {
        & $paths.ApiPython -c `
            "from app.redis_client import get_redis_client; from rq.command import send_shutdown_command; send_shutdown_command(get_redis_client(), 'teacher-assistant-windows-pilot')"
    } finally {
        Pop-Location
    }
    $workerDeadline = [DateTime]::UtcNow.AddSeconds(30)
    while ([DateTime]::UtcNow -lt $workerDeadline -and -not $workerProcess.HasExited) {
        Start-Sleep -Milliseconds 250
        $workerProcess.Refresh()
    }
    if (-not $workerProcess.HasExited) {
        Stop-PilotProcess -Paths $paths -Name "worker" -ExpectedExecutable $paths.ApiPython
    } else {
        Remove-Item -LiteralPath (Get-PilotPidPath -Paths $paths -Name "worker") -Force
        Write-Host "worker stopped."
    }
} else {
    Write-Host "worker is already stopped."
}
Push-Location $paths.ApiDirectory
try {
    & $paths.ApiPython -c `
        "from app.redis_client import get_redis_client; from rq import Worker; c=get_redis_client(); [w.register_death() for w in Worker.all(connection=c) if w.name == 'teacher-assistant-windows-pilot']"
} finally {
    Pop-Location
}
Stop-PilotProcess -Paths $paths -Name "api" -ExpectedExecutable $paths.ApiPython

if (-not $KeepLocalAi) {
    & (Join-Path $paths.RepositoryRoot "scripts\local-ai\Stop-LocalAi.ps1")
}

$redisProcess = Get-PilotOwnedProcess -Paths $paths -Name "redis" -ExpectedExecutable $paths.RedisServer
if ($null -ne $redisProcess) {
    try {
        & $paths.RedisCli -h 127.0.0.1 -p 6379 SHUTDOWN SAVE 2>$null
    } catch {
        Stop-Process -Id $redisProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Wait-Process -Id $redisProcess.Id -Timeout 15 -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Get-PilotPidPath -Paths $paths -Name "redis") -Force
    Write-Host "Redis-compatible service stopped."
} else {
    Write-Host "Redis-compatible service is already stopped."
}

$postgresExe = Join-Path $paths.PostgresBin "postgres.exe"
$pgCtl = Join-Path $paths.PostgresBin "pg_ctl.exe"

# Ask PostgreSQL to shut itself down before anything is terminated.  The reverse
# order used to wedge the machine: Stop-PilotProcess kills the postmaster's
# children first, the postmaster answers that by respawning a fresh set, and
# force-killing it mid-respawn orphans a postgres.exe that inherits the 5432
# listener.  The port then accepts connections nobody answers, so the next start
# hung on its first psql probe while this script reported success.
& $pgCtl status -D $paths.PostgresData *> $null
if ($LASTEXITCODE -eq 0) {
    & $pgCtl stop -D $paths.PostgresData -m fast -w *> $null
    if ($LASTEXITCODE -eq 0) {
        Remove-Item -LiteralPath (Get-PilotPidPath -Paths $paths -Name "postgres") `
            -Force -ErrorAction SilentlyContinue
        Write-Host "PostgreSQL stopped."
    } else {
        Write-Warning "pg_ctl could not stop PostgreSQL; terminating the tracked postmaster instead."
        Stop-PilotProcess -Paths $paths -Name "postgres" -ExpectedExecutable $postgresExe
    }
} else {
    Stop-PilotProcess -Paths $paths -Name "postgres" -ExpectedExecutable $postgresExe
}

# Never report a clean stop while something still owns 5432.  An orphan there is
# invisible until the next start hangs, which is the failure this check exists
# to make loud.
$pgPortDeadline = [DateTime]::UtcNow.AddSeconds(15)
while ((Test-PilotPort -Port 5432) -and [DateTime]::UtcNow -lt $pgPortDeadline) {
    Start-Sleep -Milliseconds 250
}
if (Test-PilotPort -Port 5432) {
    # Wrapped at the call site: PowerShell unrolls a returned array, so a single
    # orphan would arrive as a scalar and .Count would throw under StrictMode.
    $orphans = @(Get-PilotRuntimePostgresProcess -Paths $paths)
    if ($orphans.Count -eq 0) {
        throw @"
Port 5432 is still listening after PostgreSQL was stopped, and no postgres.exe
from $($paths.PostgresBin) owns it. Something outside the pilot holds that port;
starting now would hang on the first database probe.
"@
    }
    foreach ($orphan in $orphans) {
        Stop-Process -Id ([int]$orphan.ProcessId) -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
    if (Test-PilotPort -Port 5432) {
        throw "Port 5432 is still listening after clearing $($orphans.Count) orphaned postgres process(es)."
    }
    Write-Host "Cleared $($orphans.Count) orphaned postgres process(es) that still held port 5432."
}
