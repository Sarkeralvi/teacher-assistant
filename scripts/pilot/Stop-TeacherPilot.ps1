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

$pgCtl = Join-Path $paths.PostgresBin "pg_ctl.exe"
& $pgCtl status -D $paths.PostgresData *> $null
if ($LASTEXITCODE -eq 0) {
    & $pgCtl stop -D $paths.PostgresData -m fast -w
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL failed to stop cleanly."
    }
    Write-Host "PostgreSQL stopped."
} else {
    Write-Host "PostgreSQL is already stopped."
}
