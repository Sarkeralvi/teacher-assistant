param(
    [string]$ConfigPath,
    [int]$HealthTimeoutSeconds = 240,
    [ValidateSet("Qwen", "Qwen38")]
    [string]$Mode = "Qwen"
)

. (Join-Path $PSScriptRoot "Common.ps1")

$repositoryRoot = Get-RepositoryRoot
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repositoryRoot ".env.local-ai"
}
& (Join-Path $PSScriptRoot "Test-LocalAiPreflight.ps1") -ConfigPath $ConfigPath
Import-LocalAiEnvironment -Path $ConfigPath

$runtimeDirectory = Join-Path $repositoryRoot ".local-ai"
$logDirectory = Join-Path $runtimeDirectory "logs"
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

if ($Mode -eq "Qwen") {
    $binary = Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN_BINARY_PATH"
    $model = Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN_MODEL_PATH"
    $key = Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN_API_KEY"
    $port = 8080
    $alias = "qwen3.6-35b-a3b-q4km"
    $args = @(
        "-m", ('"' + $model + '"'),
        "--alias", $alias,
        "--host", "127.0.0.1",
        "--port", "$port",
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
    $pidFile = "qwen.pid"
} elseif ($Mode -eq "Qwen38") {
    $binary = Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN38_BINARY_PATH"
    $model = Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN38_MODEL_PATH"
    $key = Assert-RequiredEnvironmentValue -Name "LOCAL_QWEN38_API_KEY"
    $port = 8085
    $alias = "qwen3.8-27b-q4km"
    $args = @(
        "-m", ('"' + $model + '"'),
        "--alias", $alias,
        "--host", "127.0.0.1",
        "--port", "$port",
        "--offline",
        "-ngl", "40",
        "-c", "8192",
        "--parallel", "1",
        "--flash-attn", "on",
        "--batch-size", "256",
        "--ubatch-size", "256",
        "--threads", "12",
        "--no-mmap"
    )
    $pidFile = "qwen38.pid"
}

$env:LLAMA_API_KEY = $key
$proc = $null
try {
    $proc = Start-Process -FilePath $binary -ArgumentList $args `
        -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDirectory "$($Mode.ToLower()).stdout.log") `
        -RedirectStandardError (Join-Path $logDirectory "$($Mode.ToLower()).stderr.log")
    [IO.File]::WriteAllText((Join-Path $runtimeDirectory $pidFile), [string]$proc.Id)

    $deadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSeconds)
    $ready = $false
    while ([DateTime]::UtcNow -lt $deadline -and -not $ready) {
        if ($null -ne $proc -and $proc.HasExited) {
            throw "$Mode service exited during startup. Inspect .local-ai/logs."
        }
        try {
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" `
                -TimeoutSec 3
            $models = Invoke-RestMethod -Uri "http://127.0.0.1:$port/v1/models" `
                -Headers @{ Authorization = "Bearer $key" } -TimeoutSec 3
            $ready = @($models.data.id) -contains $alias
        } catch {
            $ready = $false
        }
        if (-not $ready) {
            Start-Sleep -Seconds 2
        }
    }

    if (-not $ready) {
        throw "$Mode did not become healthy. Inspect .local-ai/logs."
    }
    Assert-LocalAiListenerOwnership -Port $port `
        -ExpectedExecutable $binary -ExpectedProcessId $proc.Id
    Write-Host "$Mode is healthy on loopback (Port $port)."
    Write-Host "$Mode PID: $($proc.Id)"
} catch {
    if ($null -ne $proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath (Join-Path $runtimeDirectory $pidFile) -Force -ErrorAction SilentlyContinue
    throw
}
