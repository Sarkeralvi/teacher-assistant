Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-PilotRepositoryRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Get-PilotPaths {
    $repositoryRoot = Get-PilotRepositoryRoot
    $runtimeRoot = Join-Path $repositoryRoot ".local-ai\runtime"
    return [ordered]@{
        RepositoryRoot = $repositoryRoot
        RuntimeRoot = $runtimeRoot
        LogRoot = Join-Path $repositoryRoot ".local-ai\logs"
        PidRoot = Join-Path $repositoryRoot ".local-ai\pilot"
        Node = Join-Path $runtimeRoot "node-v22.14.0\node.exe"
        Npm = Join-Path $runtimeRoot "node-v22.14.0\npm.cmd"
        PostgresBin = Join-Path $runtimeRoot "postgresql-17.10\bin"
        PostgresData = Join-Path $runtimeRoot "postgres-data"
        RedisServer = Join-Path $runtimeRoot "memurai\Memurai\memurai.exe"
        RedisCli = Join-Path $runtimeRoot "memurai\Memurai\memurai-cli.exe"
        RedisData = Join-Path $runtimeRoot "redis-data"
        RedisConfig = Join-Path $PSScriptRoot "memurai.pilot.conf"
        ApiPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
        ApiDirectory = Join-Path $repositoryRoot "apps\api"
        WebDirectory = Join-Path $repositoryRoot "apps\web"
    }
}

function Import-PilotEnvironment {
    param([Parameter(Mandatory = $true)][hashtable]$Paths)

    $localAiConfig = Join-Path $Paths.RepositoryRoot ".env.local-ai"
    if (-not (Test-Path -LiteralPath $localAiConfig -PathType Leaf)) {
        throw "Local AI configuration is missing: $localAiConfig"
    }
    foreach ($line in Get-Content -LiteralPath $localAiConfig) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $trimmed.Split("=", 2)
        if ($parts.Count -ne 2 -or -not $parts[0].Trim()) {
            throw "Invalid local AI configuration line."
        }
        Set-Item -LiteralPath ("Env:" + $parts[0].Trim()) `
            -Value $parts[1].Trim().Trim('"').Trim("'")
    }

    $env:APP_ENV = "development"
    $env:DATABASE_URL = "postgresql+psycopg://teacher_assistant:teacher_assistant_dev_password@127.0.0.1:5432/teacher_assistant"
    $env:REDIS_URL = "redis://127.0.0.1:6379/0"
    $env:RQ_DEFAULT_QUEUE = "teacher-assistant-default"
    $env:RQ_WORKER_NAME = "teacher-assistant-windows-pilot"
    $env:STORAGE_BACKEND = "local"
    $env:LOCAL_STORAGE_ROOT = Join-Path $Paths.RepositoryRoot "data"
    $env:UPLOADS_DIR = Join-Path $Paths.RepositoryRoot "data\uploads"
    $env:ARTIFACTS_DIR = Join-Path $Paths.RepositoryRoot "data\artifacts"
    $env:CORS_ALLOWED_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
    $env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:8000"
    $env:BRAIN_PROVIDER = "mock"
    $nodeDirectory = Split-Path -Parent $Paths.Node
    if (-not (($env:Path -split ";") -contains $nodeDirectory)) {
        $env:Path = $nodeDirectory + ";" + $env:Path
    }
}

function Assert-PilotRuntime {
    param([Parameter(Mandatory = $true)][hashtable]$Paths)

    $requiredFiles = @(
        $Paths.Node,
        $Paths.Npm,
        (Join-Path $Paths.PostgresBin "pg_ctl.exe"),
        (Join-Path $Paths.PostgresBin "psql.exe"),
        (Join-Path $Paths.PostgresData "PG_VERSION"),
        $Paths.RedisServer,
        $Paths.RedisCli,
        $Paths.RedisConfig,
        $Paths.ApiPython
    )
    foreach ($requiredFile in $requiredFiles) {
        if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
            throw "Pilot runtime file is missing: $requiredFile"
        }
    }
    foreach ($directory in @($Paths.LogRoot, $Paths.PidRoot, $Paths.RedisData)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
}

function Get-PilotPidPath {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Paths,
        [Parameter(Mandatory = $true)][string]$Name
    )
    return (Join-Path $Paths.PidRoot ($Name + ".pid"))
}

function Get-PilotOwnedProcess {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Paths,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable
    )

    $pidPath = Get-PilotPidPath -Paths $Paths -Name $Name
    if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) {
        return $null
    }
    $processId = 0
    $rawProcessId = (Get-Content -LiteralPath $pidPath -Raw).Trim()
    if (-not [int]::TryParse($rawProcessId, [ref]$processId) -or $processId -le 0) {
        throw "$Name PID file is invalid."
    }
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        Remove-Item -LiteralPath $pidPath -Force
        return $null
    }
    $expectedPath = (Resolve-Path -LiteralPath $ExpectedExecutable).Path
    if (-not [string]::Equals($process.Path, $expectedPath, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Name PID belongs to another executable; refusing to manage it."
    }
    return $process
}

function Start-PilotProcess {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Paths,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    $existing = Get-PilotOwnedProcess -Paths $Paths -Name $Name -ExpectedExecutable $Executable
    if ($null -ne $existing) {
        Write-Host "$Name is already running (PID $($existing.Id))."
        return $existing
    }
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $Paths.LogRoot ($Name + ".stdout.log")) `
        -RedirectStandardError (Join-Path $Paths.LogRoot ($Name + ".stderr.log"))
    [IO.File]::WriteAllText(
        (Get-PilotPidPath -Paths $Paths -Name $Name),
        [string]$process.Id
    )
    return $process
}

function Stop-PilotProcess {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Paths,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable
    )

    $process = Get-PilotOwnedProcess -Paths $Paths -Name $Name -ExpectedExecutable $ExpectedExecutable
    if ($null -eq $process) {
        Write-Host "$Name is already stopped."
        return
    }

    $descendantIds = [Collections.Generic.List[int]]::new()
    $pendingParentIds = [Collections.Generic.Queue[int]]::new()
    $pendingParentIds.Enqueue($process.Id)
    while ($pendingParentIds.Count -gt 0) {
        $parentId = $pendingParentIds.Dequeue()
        foreach ($child in Get-CimInstance Win32_Process -Filter "ParentProcessId=$parentId") {
            $descendantIds.Add([int]$child.ProcessId)
            $pendingParentIds.Enqueue([int]$child.ProcessId)
        }
    }
    for ($index = $descendantIds.Count - 1; $index -ge 0; $index--) {
        Stop-Process -Id $descendantIds[$index] -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $process.Id -Force
    Wait-Process -Id $process.Id -Timeout 15 -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Get-PilotPidPath -Paths $Paths -Name $Name) -Force
    Write-Host "$Name stopped."
}

function Test-PilotPort {
    param([Parameter(Mandatory = $true)][int]$Port)
    return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-PilotHttp {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [hashtable]$Headers = @{}
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Uri -Headers $Headers -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                return
            }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    throw "Timed out waiting for $Uri"
}
