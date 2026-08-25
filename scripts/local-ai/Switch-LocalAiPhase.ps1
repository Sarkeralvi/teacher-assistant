param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("PaddleOcr", "Qwen", "Qwen38")]
    [string]$Phase,
    [string]$ConfigPath,
    [int]$HealthTimeoutSeconds = 600
)

. (Join-Path $PSScriptRoot "Common.ps1")

$repositoryRoot = Get-RepositoryRoot
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repositoryRoot ".env.local-ai"
}
Import-LocalAiEnvironment -Path $ConfigPath

# Stop every other phase before loading the requested runtime. Keeping this as
# an explicit finite set prevents Paddle and llama.cpp contending for VRAM.
foreach ($otherPhase in @("PaddleOcr", "Qwen", "Qwen38") | Where-Object { $_ -ne $Phase }) {
    & (Join-Path $PSScriptRoot "Stop-LocalAi.ps1") -Mode $otherPhase -ConfigPath $ConfigPath
}

$targetDefinition = Get-LocalAiServiceDefinition -Mode $Phase
$targetPort = $targetDefinition.Port
$targetAlias = $targetDefinition.Alias
$targetKey = [Environment]::GetEnvironmentVariable($targetDefinition.KeyVariable)

# If target phase is already healthy on loopback, return immediately
$alreadyHealthy = $false
try {
    if ($Phase -eq "PaddleOcr") {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$targetPort/health" -Headers @{ Authorization = "Bearer $targetKey" } -TimeoutSec 3
        $alreadyHealthy = ($health.status -eq "ready" -and $health.model -eq $targetAlias)
    } else {
        $models = Invoke-RestMethod -Uri "http://127.0.0.1:$targetPort/v1/models" -Headers @{ Authorization = "Bearer $targetKey" } -TimeoutSec 3
        $alreadyHealthy = @($models.data.id) -contains $targetAlias
    }
} catch {
    $alreadyHealthy = $false
}

if ($alreadyHealthy) {
    # Serving the right alias is not proof this repository started it. Without
    # this check the app would silently adopt someone else's server and contend
    # with them for its single slot and KV cache.
    $expectedExecutable = Assert-RequiredEnvironmentValue -Name $targetDefinition.BinaryVariable
    $pidPath = Join-Path (Join-Path $repositoryRoot ".local-ai") $targetDefinition.PidFileName
    if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) {
        throw ("$Phase is already serving on port $targetPort but this repository has no " +
            "PID record for it. Refusing to adopt a model server it did not start.")
    }
    $recordedProcessId = 0
    $rawRecordedProcessId = (Get-Content -LiteralPath $pidPath -Raw).Trim()
    if (-not [int]::TryParse($rawRecordedProcessId, [ref]$recordedProcessId) -or $recordedProcessId -le 0) {
        throw "$Phase PID file is invalid; refusing to adopt the listener on port $targetPort."
    }
    Assert-LocalAiListenerOwnership `
        -Port $targetPort `
        -ExpectedExecutable $expectedExecutable `
        -ExpectedProcessId $recordedProcessId
    Write-Host "$Phase is already healthy on loopback (Port $targetPort)."
    exit 0
}

$startArguments = @{
    Mode = $Phase
    HealthTimeoutSeconds = $HealthTimeoutSeconds
    ConfigPath = $ConfigPath
}
& (Join-Path $PSScriptRoot "Start-LocalAi.ps1") @startArguments

