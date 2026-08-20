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
& (Join-Path $PSScriptRoot "Test-LocalAiPreflight.ps1") -ConfigPath $ConfigPath -Mode $Mode
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
    $expectedModelHash = $env:LOCAL_QWEN38_MODEL_SHA256
    $expectedMmprojHash = $env:LOCAL_QWEN38_MMPROJ_SHA256
    $contextTokens = if ($env:LOCAL_QWEN38_CONTEXT_TOKENS) {
        [int]$env:LOCAL_QWEN38_CONTEXT_TOKENS
    } else {
        12288
    }
    if ($contextTokens -lt 12288 -or $contextTokens -gt 32768) {
        throw "LOCAL_QWEN38_CONTEXT_TOKENS must be between 12288 and 32768."
    }
    $mmproj = Join-Path ($model | Split-Path) "mmproj-Qwen3.8-27B-Q8_0.gguf"
    if (-not (Test-Path -LiteralPath $mmproj)) { throw "Qwen3.8 mmproj file is missing." }
    if ($expectedModelHash) {
        if ((Get-FileHash -LiteralPath $model -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedModelHash.ToLowerInvariant()) { throw "Qwen3.8 model SHA256 does not match LOCAL_QWEN38_MODEL_SHA256." }
    }
    if ($expectedMmprojHash) {
        if ((Get-FileHash -LiteralPath $mmproj -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedMmprojHash.ToLowerInvariant()) { throw "Qwen3.8 mmproj SHA256 does not match LOCAL_QWEN38_MMPROJ_SHA256." }
    }
    $port = 8085
    $alias = "qwen3.8-27b-q4km"
    $args = @(
        "-m", ('"' + $model + '"'),
        "--alias", $alias,
        "--mmproj", $mmproj,
        "--host", "127.0.0.1",
        "--port", "$port",
        "--offline",
        "--reasoning", "off",
        "-ngl", "40",
        "-c", "$contextTokens",
        "--image-min-tokens", "1024",
        "--image-max-tokens", "1280",
        "--parallel", "1",
        "--flash-attn", "on",
        "--batch-size", "256",
        "--ubatch-size", "256",
        "--threads", "12"
    )
    $pidFile = "qwen38.pid"
}

$env:LLAMA_API_KEY = $key
$proc = $null
$pidFullPath = Join-Path $runtimeDirectory $pidFile
Remove-Item -LiteralPath $pidFullPath -Force -ErrorAction SilentlyContinue

$stdout = Join-Path $logDirectory "$($Mode.ToLower()).stdout.log"
$stderr = Join-Path $logDirectory "$($Mode.ToLower()).stderr.log"

$argListFormatted = ($args | ForEach-Object {
    "'" + ($_ -replace "'", "''") + "'"
}) -join ", "

$launcherScript = @"
`$p = Start-Process -FilePath '$binary' -ArgumentList @($argListFormatted) -WorkingDirectory '$runtimeDirectory' -WindowStyle Hidden -PassThru -RedirectStandardOutput '$stdout' -RedirectStandardError '$stderr'
[IO.File]::WriteAllText('$pidFullPath', [string]`$p.Id)
"@

$encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($launcherScript))
$null = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand $encoded"
    CurrentDirectory = $runtimeDirectory
}

$deadline = [DateTime]::UtcNow.AddSeconds(10)
while ([DateTime]::UtcNow -lt $deadline -and -not (Test-Path -LiteralPath $pidFullPath -PathType Leaf)) {
    Start-Sleep -Milliseconds 100
}

if (-not (Test-Path -LiteralPath $pidFullPath -PathType Leaf)) {
    throw "Failed to start $Mode launcher or write PID file."
}

$procId = [int](Get-Content -LiteralPath $pidFullPath -Raw).Trim()
$proc = Get-Process -Id $procId -ErrorAction SilentlyContinue

try {
    $deadline = [DateTime]::UtcNow.AddSeconds($HealthTimeoutSeconds)
    $ready = $false
    while ([DateTime]::UtcNow -lt $deadline -and -not $ready) {
        if ($null -ne $proc -and $proc.HasExited) {
            throw "$Mode service exited during startup. Inspect .local-ai/logs."
        }
        try {
            $null = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 3
            $models = Invoke-RestMethod -Uri "http://127.0.0.1:$port/v1/models" -Headers @{ Authorization = "Bearer $key" } -TimeoutSec 3
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
    Assert-LocalAiListenerOwnership -Port $port -ExpectedExecutable $binary -ExpectedProcessId $proc.Id
    Write-Host "$Mode is healthy on loopback (Port $port)."
    Write-Host "$Mode PID: $($proc.Id)"

    # Informational only: this machine has a documented GPU-instability history,
    # so low VRAM headroom is worth surfacing at every startup rather than only
    # discovering it during a crash. Never blocks startup.
    try {
        $vramFields = (nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits) -split ','
        $vramUsedMib = [int]$vramFields[0].Trim()
        $vramTotalMib = [int]$vramFields[1].Trim()
        $vramFreeMib = $vramTotalMib - $vramUsedMib
        Write-Host "$Mode VRAM: $vramUsedMib / $vramTotalMib MiB used ($vramFreeMib MiB free)."
        if ($vramFreeMib -lt 1000) {
            Write-Warning ("$Mode is leaving only $vramFreeMib MiB of VRAM headroom. " +
                "This machine has a documented GPU-instability history; low headroom raises " +
                "OOM/crash risk under load. Consider a lower -ngl value if this recurs.")
        }
    } catch {
        Write-Host "VRAM check skipped (nvidia-smi unavailable)." -ForegroundColor DarkGray
    }
} catch {
    if ($null -ne $proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath (Join-Path $runtimeDirectory $pidFile) -Force -ErrorAction SilentlyContinue
    throw
}
